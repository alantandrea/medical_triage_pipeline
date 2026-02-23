"""
Step 1: Intake - Download and validate report content.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..state import PipelineState

logger = logging.getLogger(__name__)


async def intake_node(
    state: PipelineState,
    aws_client: Any,
    redis_client: Any,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Download PDF/image from S3 and store in Redis for processing.
    
    Inputs:
        - report_id, patient_id, report_type from state
        - pdf_url, image_url from pending report
    
    Outputs:
        - pdf_bytes, image_bytes, image_format
        - report_date, reporting_source, is_final
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    
    logger.info(f"[{tenant_id}] Intake: Processing report {report_id}")
    
    try:
        # Get pending report details (passed via state or fetch)
        pdf_url = state.get("pdf_url")
        image_url = state.get("image_url")
        
        # Download PDF if available
        pdf_bytes = None
        if pdf_url:
            pdf_bytes = await aws_client.download_pdf(pdf_url)
            logger.info(f"[{tenant_id}] Downloaded PDF: {len(pdf_bytes)} bytes")
        
        # Download image if available (radiology)
        image_bytes = None
        image_format = None
        if image_url:
            image_bytes = await aws_client.download_image(image_url)
            # Guard against empty or corrupt image data
            if image_bytes and len(image_bytes) > 8:
                # Detect format from content
                if image_bytes[:3] == b'\xff\xd8\xff':
                    image_format = "jpeg"
                elif image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                    image_format = "png"
                logger.info(f"[{tenant_id}] Downloaded image: {len(image_bytes)} bytes ({image_format})")
            else:
                logger.warning(
                    f"[{tenant_id}] Image data empty or too small ({len(image_bytes) if image_bytes else 0} bytes) "
                    f"for report {report_id}, skipping image analysis"
                )
                image_bytes = None
        
        # Update state
        state["pdf_bytes"] = pdf_bytes
        state["image_bytes"] = image_bytes
        state["image_format"] = image_format
        state["processing_started"] = datetime.now(timezone.utc)
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["intake"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            pdf_size = len(pdf_bytes) if pdf_bytes else 0
            img_size = len(image_bytes) if image_bytes else 0
            await pipeline_logger.log_step(
                state=state, step="intake", duration_ms=duration_ms,
                synopsis=f"Downloaded PDF ({pdf_size}B) and image ({img_size}B, {image_format or 'none'})",
                details={"pdf_size": pdf_size, "image_size": img_size, "image_format": image_format},
            )
        
        logger.info(f"[{tenant_id}] Intake complete: {duration_ms}ms")
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Intake failed: {e}")
        state.setdefault("errors", []).append(f"Intake: {str(e)}")
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="intake", error=str(e),
                synopsis=f"Intake failed: {e}",
            )
    
    return state
