"""
Patient Sync Job - Daily synchronization of patients from AWS API to MongoDB.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from ..clients.aws_api import AWSAPIClient
from ..clients.mongodb_client import MongoDBClient
from ..clients.redis_client import RedisClient
from ..config import settings

logger = logging.getLogger(__name__)


class PatientSyncJob:
    """
    Synchronizes patient data from AWS API to local MongoDB.
    
    Features:
    - Full sync: Fetches all patients and upserts to MongoDB
    - Incremental sync: Only fetches patients updated since last sync
    - Distributed lock: Prevents concurrent sync runs
    - Progress tracking: Logs sync progress and statistics
    """
    
    LOCK_NAME = "patient_sync"
    LOCK_TTL = 600  # 10 minutes
    
    def __init__(
        self,
        aws_client: Optional[AWSAPIClient] = None,
        mongodb_client: Optional[MongoDBClient] = None,
        redis_client: Optional[RedisClient] = None,
        tenant_id: Optional[str] = None
    ):
        self._aws = aws_client
        self._mongodb = mongodb_client
        self._redis = redis_client
        self._tenant_id = tenant_id or settings.tenant_id
        self._owns_clients = False
    
    async def _ensure_clients(self) -> None:
        """Initialize clients if not provided."""
        if not self._aws:
            self._aws = AWSAPIClient()
            self._owns_clients = True
        
        if not self._mongodb:
            self._mongodb = MongoDBClient()
            await self._mongodb.connect()
            self._owns_clients = True
        
        if not self._redis:
            self._redis = RedisClient()
            await self._redis.connect()
            self._owns_clients = True
    
    async def _cleanup_clients(self) -> None:
        """Close clients if we own them."""
        if self._owns_clients:
            if self._aws:
                await self._aws.close()
            if self._mongodb:
                await self._mongodb.close()
            if self._redis:
                await self._redis.close()

    async def run_full_sync(self) -> dict:
        """
        Perform a full patient sync from AWS to MongoDB.
        
        Returns:
            dict with sync statistics
        """
        await self._ensure_clients()
        
        # Acquire distributed lock
        lock_acquired = await self._redis.acquire_lock(self.LOCK_NAME, self.LOCK_TTL)
        if not lock_acquired:
            logger.warning("Patient sync already running, skipping")
            return {"status": "skipped", "reason": "lock_held"}
        
        try:
            start_time = datetime.now(timezone.utc)
            logger.info(f"Starting full patient sync for tenant {self._tenant_id}")
            
            # Fetch all patients from AWS
            patients = await self._aws.get_all_patients(limit=10000)
            total = len(patients)
            logger.info(f"Fetched {total} patients from AWS API")
            
            # Upsert to MongoDB
            synced = 0
            errors = 0
            
            for patient in patients:
                try:
                    await self._mongodb.upsert_patient(self._tenant_id, patient)
                    synced += 1
                    
                    if synced % 100 == 0:
                        logger.info(f"Synced {synced}/{total} patients")
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"Failed to sync patient {patient.patient_id}: {e}")
            
            # Record sync metadata
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            await self._record_sync_metadata(
                sync_type="full",
                total=total,
                synced=synced,
                errors=errors,
                duration=duration
            )
            
            result = {
                "status": "completed",
                "sync_type": "full",
                "tenant_id": self._tenant_id,
                "total_fetched": total,
                "synced": synced,
                "errors": errors,
                "duration_seconds": duration,
                "completed_at": end_time.isoformat()
            }
            
            logger.info(f"Patient sync completed: {synced}/{total} synced, {errors} errors, {duration:.1f}s")
            return result
            
        finally:
            await self._redis.release_lock(self.LOCK_NAME)
            await self._cleanup_clients()

    async def run_incremental_sync(self, since: Optional[datetime] = None) -> dict:
        """
        Perform incremental patient sync (only updated patients).
        
        Args:
            since: Only sync patients updated after this time.
                   If None, uses last sync time from metadata.
        """
        await self._ensure_clients()
        
        lock_acquired = await self._redis.acquire_lock(self.LOCK_NAME, self.LOCK_TTL)
        if not lock_acquired:
            logger.warning("Patient sync already running, skipping")
            return {"status": "skipped", "reason": "lock_held"}
        
        try:
            start_time = datetime.now(timezone.utc)
            
            # Get last sync time if not provided
            if not since:
                meta = await self._get_sync_metadata()
                last_sync = meta.get("last_sync_time")
                if last_sync:
                    since = datetime.fromisoformat(last_sync)
            
            logger.info(f"Starting incremental patient sync since {since}")
            
            # For now, fetch all and filter (AWS API may not support since param)
            # In production, add since parameter to AWS API
            patients = await self._aws.get_all_patients(limit=10000)
            
            # Filter to only updated patients
            if since:
                patients = [
                    p for p in patients
                    if p.updated_at and p.updated_at > since
                ]
            
            total = len(patients)
            logger.info(f"Found {total} patients updated since {since}")
            
            synced = 0
            errors = 0
            
            for patient in patients:
                try:
                    await self._mongodb.upsert_patient(self._tenant_id, patient)
                    synced += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Failed to sync patient {patient.patient_id}: {e}")
            
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            await self._record_sync_metadata(
                sync_type="incremental",
                total=total,
                synced=synced,
                errors=errors,
                duration=duration
            )
            
            result = {
                "status": "completed",
                "sync_type": "incremental",
                "tenant_id": self._tenant_id,
                "since": since.isoformat() if since else None,
                "total_updated": total,
                "synced": synced,
                "errors": errors,
                "duration_seconds": duration,
                "completed_at": end_time.isoformat()
            }
            
            logger.info(f"Incremental sync completed: {synced}/{total} synced")
            return result
            
        finally:
            await self._redis.release_lock(self.LOCK_NAME)
            await self._cleanup_clients()

    async def _record_sync_metadata(
        self,
        sync_type: str,
        total: int,
        synced: int,
        errors: int,
        duration: float
    ) -> None:
        """Record sync metadata in Redis."""
        meta_key = f"patient_sync:{self._tenant_id}:metadata"
        await self._redis.client.hset(meta_key, mapping={
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "last_sync_type": sync_type,
            "last_total": str(total),
            "last_synced": str(synced),
            "last_errors": str(errors),
            "last_duration": str(duration)
        })
    
    async def _get_sync_metadata(self) -> dict:
        """Get sync metadata from Redis."""
        meta_key = f"patient_sync:{self._tenant_id}:metadata"
        return await self._redis.client.hgetall(meta_key) or {}
    
    async def get_status(self) -> dict:
        """Get current sync status and statistics."""
        await self._ensure_clients()
        
        try:
            meta = await self._get_sync_metadata()
            patient_count = await self._mongodb.get_patient_count(self._tenant_id)
            
            return {
                "tenant_id": self._tenant_id,
                "patient_count": patient_count,
                "last_sync_time": meta.get("last_sync_time"),
                "last_sync_type": meta.get("last_sync_type"),
                "last_synced": int(meta.get("last_synced", 0)),
                "last_errors": int(meta.get("last_errors", 0)),
                "last_duration": float(meta.get("last_duration", 0))
            }
        finally:
            await self._cleanup_clients()


async def run_patient_sync_cli():
    """CLI entry point for patient sync job."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Patient Sync Job")
    parser.add_argument(
        "--mode",
        choices=["full", "incremental", "status"],
        default="incremental",
        help="Sync mode"
    )
    parser.add_argument(
        "--tenant-id",
        default=settings.tenant_id,
        help="Tenant ID"
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    job = PatientSyncJob(tenant_id=args.tenant_id)
    
    if args.mode == "full":
        result = await job.run_full_sync()
    elif args.mode == "incremental":
        result = await job.run_incremental_sync()
    else:
        result = await job.get_status()
    
    print(result)


if __name__ == "__main__":
    asyncio.run(run_patient_sync_cli())
