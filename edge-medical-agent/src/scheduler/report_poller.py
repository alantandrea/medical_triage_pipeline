"""
APScheduler-based report poller.

Polls the AWS API for pending reports every minute and queues them
for processing by the pipeline worker.

Architecture:
- Scheduler Pod: Polls AWS API, queues reports to Redis
- Worker Pod: Consumes from Redis queue, runs LangGraph pipeline
- API Pod: Serves REST endpoints for manual triggers and status
"""
import asyncio
import logging
import json
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import settings
from ..clients.aws_api import AWSAPIClient
from ..clients.redis_client import RedisClient

logger = logging.getLogger(__name__)

# Redis queue keys
REPORT_QUEUE = "medgemma:report_queue"
NOTE_QUEUE = "medgemma:note_queue"
POLL_LOCK = "medgemma:poll_lock"


class ReportPoller:
    """
    Polls AWS API for pending reports and notes, queues them for processing.
    
    Uses Redis distributed lock to ensure only one poller runs at a time
    (important if multiple scheduler replicas are accidentally deployed).
    """
    
    def __init__(
        self,
        poll_interval_seconds: int = 60,
        tenant_id: str = "practice-001"
    ):
        self.poll_interval = poll_interval_seconds
        self.tenant_id = tenant_id
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.aws_client: Optional[AWSAPIClient] = None
        self.redis_client: Optional[RedisClient] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the polling scheduler."""
        logger.info(f"Starting report poller (interval={self.poll_interval}s)")
        
        # Initialize clients
        self.aws_client = AWSAPIClient()
        self.redis_client = RedisClient()
        await self.redis_client.connect()
        
        # Create scheduler
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self._poll_and_queue,
            trigger=IntervalTrigger(seconds=self.poll_interval),
            id="report_poller",
            name="Poll AWS for pending reports",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
        )
        
        self.scheduler.start()
        self._running = True
        
        # Run initial poll immediately
        await self._poll_and_queue()
        
        logger.info("Report poller started successfully")
    
    async def stop(self) -> None:
        """Stop the polling scheduler."""
        logger.info("Stopping report poller...")
        self._running = False
        
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        
        if self.redis_client:
            await self.redis_client.close()
        
        if self.aws_client:
            await self.aws_client.close()
        
        logger.info("Report poller stopped")
    
    async def _poll_and_queue(self) -> None:
        """Poll for pending reports and queue them."""
        # Backpressure check: skip poll if queues are already full
        try:
            report_depth = await self.redis_client.client.llen(REPORT_QUEUE)
            note_depth = await self.redis_client.client.llen(NOTE_QUEUE)
            total_depth = report_depth + note_depth
            
            if total_depth >= settings.queue_backpressure_threshold:
                logger.info(
                    f"Backpressure: queue depth {total_depth} "
                    f"(reports={report_depth}, notes={note_depth}) "
                    f">= threshold {settings.queue_backpressure_threshold}, skipping poll"
                )
                return
        except Exception as e:
            logger.warning(f"Could not check queue depth, proceeding with poll: {e}")
        
        # Acquire distributed lock to prevent duplicate polling
        lock_acquired = await self.redis_client.acquire_lock(
            POLL_LOCK,
            ttl_seconds=max(self.poll_interval - 5, 10)
        )
        
        if not lock_acquired:
            logger.warning("Could not acquire poll lock - another poller is running")
            return
        
        try:
            await self._poll_reports()
            await self._poll_notes()
        except Exception as e:
            logger.error(f"Polling failed: {e}")
        finally:
            await self.redis_client.release_lock(POLL_LOCK)
    
    async def _poll_reports(self) -> None:
        """Poll for pending reports and queue them."""
        try:
            reports = await self.aws_client.get_pending_reports(limit=50)
            
            if not reports:
                logger.debug("No pending reports")
                return
            
            logger.info(f"Found {len(reports)} pending reports")
            
            queued = 0
            for report in reports:
                # Create queue item
                queue_item = {
                    "type": "report",
                    "tenant_id": self.tenant_id,
                    "report_id": report.report_id,
                    "patient_id": report.patient_id,
                    "report_type": report.report_type,
                    "pdf_url": report.report_pdf_url,
                    "image_url": report.report_image_url,
                    "severity": report.severity,
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                }
                
                # Push to Redis queue (FIFO)
                await self.redis_client.client.lpush(
                    REPORT_QUEUE,
                    json.dumps(queue_item)
                )
                queued += 1
            
            logger.info(f"Queued {queued} reports for processing")
            
        except Exception as e:
            logger.error(f"Failed to poll reports: {e}")
    
    async def _poll_notes(self) -> None:
        """Poll for pending patient notes and queue them."""
        try:
            notes = await self.aws_client.get_pending_notes(limit=50)
            
            if not notes:
                logger.debug("No pending notes")
                return
            
            logger.info(f"Found {len(notes)} pending notes")
            
            queued = 0
            for note in notes:
                # Build vitals dict from top-level PendingNote fields
                vitals = {}
                for field in ("temperature", "pain_scale", "sp02", "systolic",
                              "diastolic", "weight", "blood_sugar_level",
                              "heart_rate", "hemoglobin_a1c"):
                    val = getattr(note, field, None)
                    if val is not None:
                        vitals[field] = val

                queue_item = {
                    "type": "note",
                    "tenant_id": self.tenant_id,
                    "note_id": note.note_id,
                    "patient_id": note.patient_id,
                    "note_text": note.note_text,
                    "vitals": vitals or None,
                    "symptoms": note.symptoms,
                    "urgency_indicators": note.urgency_indicators,
                    "has_urgency": note.has_urgency,
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                }
                
                await self.redis_client.client.lpush(
                    NOTE_QUEUE,
                    json.dumps(queue_item)
                )
                queued += 1
            
            logger.info(f"Queued {queued} notes for processing")
            
        except Exception as e:
            logger.error(f"Failed to poll notes: {e}")


async def main():
    """Main entry point for scheduler pod."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    poll_interval = int(settings.poll_interval_seconds or 60)
    poller = ReportPoller(poll_interval_seconds=poll_interval)
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def shutdown_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(poller.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_handler)
    
    try:
        await poller.start()
        
        # Keep running until stopped
        while poller._running:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Poller crashed: {e}")
        sys.exit(1)
    finally:
        await poller.stop()


if __name__ == "__main__":
    asyncio.run(main())
