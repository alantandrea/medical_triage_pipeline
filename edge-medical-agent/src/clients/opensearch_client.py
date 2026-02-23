"""
OpenSearch pipeline logger - common library for all pipeline steps.

Every pipeline node calls `log_step()` to write a structured document
to OpenSearch, creating a complete flow trace per report that can be
queried and visualized in OpenSearch Dashboards.

Index pattern: pipeline-logs-YYYY.MM.DD (daily rotation)

Usage in any pipeline node:
    from ...clients.opensearch_client import PipelineLogger
    
    async def my_node(state, ..., pipeline_logger=None):
        await pipeline_logger.log_step(
            state=state,
            step="classify",
            synopsis="Classified report as lab using 27B model",
            details={"classified_type": "lab", "text_length": 4200},
        )
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from opensearchpy import AsyncOpenSearch

from ..config import settings

logger = logging.getLogger(__name__)


class PipelineLogger:
    """
    Async OpenSearch client for pipeline flow logging.
    
    Each call to log_step() indexes one document capturing what a
    pipeline step did, its key outputs, errors, and timing.
    Documents are fire-and-forget — failures are logged but never
    block the pipeline.
    """

    def __init__(self):
        self._client: Optional[AsyncOpenSearch] = None

    async def connect(self) -> None:
        """Initialize the async OpenSearch connection."""
        try:
            url = settings.opensearch_url
            self._client = AsyncOpenSearch(
                hosts=[url],
                use_ssl=url.startswith("https"),
                verify_certs=settings.opensearch_verify_certs,
                ssl_show_warn=settings.opensearch_verify_certs,
                timeout=5,
                max_retries=1,
            )
            # Quick connectivity check
            info = await self._client.info()
            logger.info(f"OpenSearch connected: {info.get('version', {}).get('number', '?')}")
        except Exception as e:
            logger.warning(f"OpenSearch connection failed (logging disabled): {e}")
            self._client = None

    async def close(self) -> None:
        """Close the OpenSearch connection."""
        if self._client:
            await self._client.close()
            self._client = None

    async def health_check(self) -> bool:
        """Check if OpenSearch is reachable."""
        if not self._client:
            return False
        try:
            await self._client.info()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Main API — called by every pipeline node
    # ------------------------------------------------------------------

    async def log_step(
        self,
        state: Dict[str, Any],
        step: str,
        synopsis: str,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """
        Index a single pipeline step document.

        Args:
            state:       Current PipelineState (we pull IDs from it)
            step:        Step name (intake, classify, extract, etc.)
            synopsis:    One-liner describing what happened
            details:     Key outputs worth capturing (keep it brief)
            error:       Error message if the step failed
            duration_ms: How long the step took
        """
        if not self._client:
            return  # OpenSearch not available, skip silently

        now = datetime.now(timezone.utc)
        index = f"pipeline-logs-{now.strftime('%Y.%m.%d')}"

        doc = {
            "@timestamp": now.isoformat(),
            "tenant_id": state.get("tenant_id", ""),
            "report_id": state.get("report_id", ""),
            "patient_id": state.get("patient_id", 0),
            "report_type": state.get("report_type") or state.get("classified_type", ""),
            "step": step,
            "synopsis": synopsis,
            "duration_ms": duration_ms,
            "error": error,
            "priority_level": state.get("priority_level"),
            "final_score": state.get("final_score"),
        }

        if details:
            doc["details"] = details

        try:
            await self._client.index(index=index, body=doc)
        except Exception as e:
            # Never let logging failures crash the pipeline
            logger.debug(f"OpenSearch index failed for step={step}: {e}")

    # ------------------------------------------------------------------
    # Convenience: log scheduler / worker events outside the pipeline
    # ------------------------------------------------------------------

    async def log_event(
        self,
        event: str,
        synopsis: str,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log a non-pipeline event (scheduler skip, worker start, etc.)."""
        if not self._client:
            return

        now = datetime.now(timezone.utc)
        index = f"pipeline-logs-{now.strftime('%Y.%m.%d')}"

        doc = {
            "@timestamp": now.isoformat(),
            "tenant_id": settings.tenant_id,
            "step": event,
            "synopsis": synopsis,
            "error": error,
        }
        if details:
            doc["details"] = details

        try:
            await self._client.index(index=index, body=doc)
        except Exception:
            pass
