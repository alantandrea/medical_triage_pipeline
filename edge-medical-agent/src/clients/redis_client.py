"""
Redis client for in-flight report state and LOINC reference data.
"""
import base64
import json
import logging
from typing import Optional, List
import redis.asyncio as redis

from ..models import PatientReport, ReportFinding
from ..config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client for state management."""
    
    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.redis_url
        self._client: Optional[redis.Redis] = None
    
    async def connect(self) -> None:
        """Establish Redis connection."""
        self._client = redis.from_url(self.url, decode_responses=True)
        await self._client.ping()
        logger.info("Connected to Redis")
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")
    
    @property
    def client(self) -> redis.Redis:
        """Get the underlying Redis client."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return self._client
    
    # ==================== Report State Management ====================
    
    def _report_key(self, tenant_id: str, report_id: str) -> str:
        """Generate Redis key for report state."""
        return f"report:{tenant_id}:{report_id}"
    
    async def store_report_state(
        self,
        tenant_id: str,
        report: PatientReport,
        ttl_seconds: int = 3600
    ) -> None:
        """Store in-flight report state."""
        key = self._report_key(tenant_id, report.report_id)
        # Exclude binary data from JSON serialization
        data = report.model_dump(exclude={"lab_report_doc", "radiology_image"})
        data["report_date"] = data["report_date"].isoformat()
        
        await self._client.setex(key, ttl_seconds, json.dumps(data))
        
        # Store binary data separately if present (base64 encoded to avoid UTF-8 corruption)
        if report.lab_report_doc:
            await self._client.setex(
                f"{key}:pdf",
                ttl_seconds,
                base64.b64encode(report.lab_report_doc).decode("ascii")
            )
        if report.radiology_image:
            await self._client.setex(
                f"{key}:image",
                ttl_seconds,
                base64.b64encode(report.radiology_image).decode("ascii")
            )

    async def get_report_state(
        self,
        tenant_id: str,
        report_id: str
    ) -> Optional[PatientReport]:
        """Retrieve in-flight report state."""
        key = self._report_key(tenant_id, report_id)
        data = await self._client.get(key)
        if not data:
            return None
        
        report_data = json.loads(data)
        
        # Retrieve binary data if exists (base64 decode)
        pdf_data = await self._client.get(f"{key}:pdf")
        image_data = await self._client.get(f"{key}:image")
        
        if pdf_data:
            report_data["lab_report_doc"] = base64.b64decode(pdf_data)
        if image_data:
            report_data["radiology_image"] = base64.b64decode(image_data)
        
        return PatientReport(**report_data)
    
    async def delete_report_state(self, tenant_id: str, report_id: str) -> None:
        """Remove report state after processing."""
        key = self._report_key(tenant_id, report_id)
        await self._client.delete(key, f"{key}:pdf", f"{key}:image")
    
    # ==================== Finding Storage ====================
    
    def _findings_key(self, tenant_id: str, report_id: str) -> str:
        """Generate Redis key for findings list."""
        return f"findings:{tenant_id}:{report_id}"
    
    async def add_finding(
        self,
        tenant_id: str,
        finding: ReportFinding,
        ttl_seconds: int = 3600
    ) -> None:
        """Add a finding to the report's findings list."""
        key = self._findings_key(tenant_id, finding.report_id)
        data = finding.model_dump()
        data["created_at"] = data["created_at"].isoformat()
        
        await self._client.rpush(key, json.dumps(data))
        await self._client.expire(key, ttl_seconds)
    
    async def get_findings(
        self,
        tenant_id: str,
        report_id: str
    ) -> List[ReportFinding]:
        """Get all findings for a report."""
        key = self._findings_key(tenant_id, report_id)
        items = await self._client.lrange(key, 0, -1)
        return [ReportFinding(**json.loads(item)) for item in items]
    
    # ==================== Processing Lock ====================
    
    async def acquire_lock(
        self,
        lock_name: str,
        ttl_seconds: int = 300
    ) -> bool:
        """Acquire a distributed lock."""
        key = f"lock:{lock_name}"
        return await self._client.set(key, "1", nx=True, ex=ttl_seconds)
    
    async def release_lock(self, lock_name: str) -> None:
        """Release a distributed lock."""
        await self._client.delete(f"lock:{lock_name}")
    
    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self._client.ping()
            return True
        except Exception:
            return False
