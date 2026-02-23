"""
Pipeline worker that consumes reports from Redis queue and processes them.

Architecture:
- Scheduler Pod: Polls AWS API, queues reports to Redis
- Worker Pod: Consumes from Redis queue, runs LangGraph pipeline (THIS)
- API Pod: Serves REST endpoints for manual triggers and status
"""
import asyncio
import logging
import json
import signal
import sys
from datetime import datetime, timezone
from typing import Optional, Any

from ..config import settings
from ..clients import (
    AWSAPIClient,
    MongoDBClient,
    RedisClient,
    MedGemma27BClient,
    MedGemma4BClient,
    LOINCClient,
    PipelineLogger,
)
from ..pipeline.graph import create_triage_pipeline
from ..reporting.service import NotificationService

logger = logging.getLogger(__name__)

# Redis queue keys (must match scheduler)
REPORT_QUEUE = "medgemma:report_queue"
NOTE_QUEUE = "medgemma:note_queue"
PROCESSING_SET = "medgemma:processing"

# Dead-letter queue keys
REPORT_DLQ = "medgemma:report_dlq"
NOTE_DLQ = "medgemma:note_dlq"

# Retry config
MAX_RETRIES = settings.dlq_max_retries


class PipelineWorker:
    """
    Consumes reports/notes from Redis queue and processes them through
    the LangGraph pipeline.
    
    Features:
    - FIFO processing from Redis queue
    - Retry with exponential backoff (up to MAX_RETRIES attempts)
    - Dead-letter queue for items that exceed retry limit
    - Deduplication guard on reports
    - Graceful shutdown handling
    - Concurrent processing limit
    """
    
    def __init__(self, concurrency: int = 1):
        self.concurrency = concurrency
        self._running = False
        self._tasks: list[asyncio.Task] = []
        
        # Clients (initialized in start())
        self.aws_client: Optional[AWSAPIClient] = None
        self.mongodb_client: Optional[MongoDBClient] = None
        self.redis_client: Optional[RedisClient] = None
        self.medgemma_27b: Optional[MedGemma27BClient] = None
        self.medgemma_4b: Optional[MedGemma4BClient] = None
        self.loinc_client: Optional[LOINCClient] = None
        self.notification_service: Optional[NotificationService] = None
        self.pipeline_logger: Optional[PipelineLogger] = None
        self.pipeline: Optional[Any] = None
    
    async def start(self) -> None:
        """Initialize clients and start processing."""
        logger.info(f"Starting pipeline worker (concurrency={self.concurrency})")
        
        # Initialize all clients
        self.aws_client = AWSAPIClient()
        self.mongodb_client = MongoDBClient()
        self.redis_client = RedisClient()
        self.medgemma_27b = MedGemma27BClient()
        self.medgemma_4b = MedGemma4BClient()
        self.notification_service = NotificationService()
        self.pipeline_logger = PipelineLogger()
        
        # Connect async clients
        await self.mongodb_client.connect()
        await self.redis_client.connect()
        await self.pipeline_logger.connect()
        
        # Initialize LOINC client after Redis is connected (needs raw redis connection)
        self.loinc_client = LOINCClient(self.redis_client.client, settings.tenant_id)
        
        # Create pipeline
        self.pipeline = create_triage_pipeline(
            aws_client=self.aws_client,
            mongodb_client=self.mongodb_client,
            redis_client=self.redis_client,
            medgemma_27b=self.medgemma_27b,
            medgemma_4b=self.medgemma_4b,
            loinc_client=self.loinc_client,
            notification_service=self.notification_service,
            pipeline_logger=self.pipeline_logger,
        )
        
        self._running = True
        
        # Start worker tasks
        for i in range(self.concurrency):
            task = asyncio.create_task(self._worker_loop(worker_id=i))
            self._tasks.append(task)
        
        logger.info("Pipeline worker started successfully")
    
    async def stop(self) -> None:
        """Gracefully stop the worker."""
        logger.info("Stopping pipeline worker...")
        self._running = False
        
        # Cancel worker tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close clients
        if self.pipeline_logger:
            await self.pipeline_logger.close()
        if self.medgemma_27b:
            await self.medgemma_27b.close()
        if self.medgemma_4b:
            await self.medgemma_4b.close()
        if self.aws_client:
            await self.aws_client.close()
        if self.mongodb_client:
            await self.mongodb_client.close()
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Pipeline worker stopped")
    
    async def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop - consume and process queue items."""
        logger.info(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Try to get a report first, then notes
                item = await self._dequeue_item()
                
                if item is None:
                    # No items, wait before checking again
                    await asyncio.sleep(1)
                    continue
                
                # Process the item
                await self._process_item(item, worker_id)
                
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(5)  # Back off on error
        
        logger.info(f"Worker {worker_id} stopped")
    
    async def _dequeue_item(self) -> Optional[dict]:
        """Get next item from queue (reports have priority over notes)."""
        # Try reports first
        result = await self.redis_client.client.rpop(REPORT_QUEUE)
        if result:
            return json.loads(result)
        
        # Then try notes
        result = await self.redis_client.client.rpop(NOTE_QUEUE)
        if result:
            return json.loads(result)
        
        return None
    
    async def _process_item(self, item: dict, worker_id: int) -> None:
        """Process a single queue item with retry and DLQ support."""
        item_type = item.get("type", "report")
        item_id = item.get("report_id") or item.get("note_id")
        retry_count = item.get("retry_count", 0)
        
        logger.info(f"Worker {worker_id}: Processing {item_type} {item_id} (attempt {retry_count + 1})")
        start_time = datetime.now(timezone.utc)
        
        try:
            if item_type == "report":
                await self._process_report(item)
            elif item_type == "note":
                await self._process_note(item)
            else:
                logger.warning(f"Unknown item type: {item_type}")
                return
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(f"Worker {worker_id}: Completed {item_type} {item_id} in {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Worker {worker_id}: Failed to process {item_type} {item_id}: {e}")
            await self._handle_failure(item, item_type, item_id, retry_count, e)
    
    async def _handle_failure(
        self, item: dict, item_type: str, item_id: str, retry_count: int, error: Exception
    ) -> None:
        """Handle processing failure: retry with backoff or move to DLQ."""
        retry_count += 1
        
        if retry_count < MAX_RETRIES:
            # Exponential backoff: 2s, 4s, 8s
            backoff = 2 ** retry_count
            logger.warning(
                f"Retrying {item_type} {item_id} in {backoff}s "
                f"(attempt {retry_count + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(backoff)
            
            # Re-queue with updated retry count
            item["retry_count"] = retry_count
            queue_key = REPORT_QUEUE if item_type == "report" else NOTE_QUEUE
            await self.redis_client.client.lpush(queue_key, json.dumps(item))
        else:
            # Max retries exceeded — move to dead-letter queue
            dlq_key = REPORT_DLQ if item_type == "report" else NOTE_DLQ
            dlq_item = {
                **item,
                "retry_count": retry_count,
                "last_error": str(error),
                "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.redis_client.client.lpush(dlq_key, json.dumps(dlq_item))
            logger.error(
                f"Moved {item_type} {item_id} to DLQ after {retry_count} failed attempts: {error}"
            )
    
    async def _process_report(self, item: dict) -> None:
        """Process a report through the LangGraph pipeline."""
        # Deduplication guard — skip if already processed
        if await self.mongodb_client.is_report_processed(item["report_id"]):
            logger.info(f"Report {item['report_id']} already processed, skipping (dedup)")
            return
        
        result = await self.pipeline.process_report(
            tenant_id=item["tenant_id"],
            report_id=item["report_id"],
            patient_id=item["patient_id"],
            report_type=item["report_type"],
            pdf_url=item.get("pdf_url"),
            image_url=item.get("image_url"),
        )
        
        # Mark as processed in AWS
        await self.aws_client.mark_report_processed(item["report_id"])
        
        # Log result
        logger.info(
            f"Report {item['report_id']}: "
            f"score={result.get('final_score', 0)}, "
            f"level={result.get('priority_level', 'unknown')}, "
            f"errors={len(result.get('errors', []))}"
        )
    
    async def _process_note(self, item: dict) -> None:
        """Process a patient note (simplified flow, no image analysis)."""
        # Deduplication guard — skip if already processed
        if await self.mongodb_client.is_note_processed(item["tenant_id"], item["note_id"]):
            logger.info(f"Note {item['note_id']} already processed, skipping (dedup)")
            return

        note_text = item.get("note_text", "")
        vitals = item.get("vitals", {})
        
        # Build context from vitals
        vitals_context = ""
        if vitals:
            vitals_context = "Vitals: " + ", ".join(
                f"{k}={v}" for k, v in vitals.items() if v is not None
            )
        
        # Analyze with 27B
        result = await self.medgemma_27b.analyze_lab_report(
            report_text=note_text,
            patient_context=vitals_context,
        )
        
        # Store in MongoDB
        await self.mongodb_client.store_note_result(
            tenant_id=item["tenant_id"],
            note_id=item["note_id"],
            patient_id=item["patient_id"],
            analysis=result.model_dump(),
        )
        
        # Mark as processed (pass result dict matching API contract)
        await self.aws_client.mark_note_processed(
            note_id=item["note_id"],
            result={
                "ai_priority_score": result.urgency_score,
                "ai_interpretation": result.summary,
            },
        )
        
        # Send email notifications (same thresholds as reports)
        score = result.urgency_score
        if self.notification_service and settings.clinical_notification_email:
            try:
                # Fetch patient history for email context
                patient_history = []
                if score >= settings.threshold_important and self.mongodb_client:
                    try:
                        patient_history = await self.mongodb_client.get_patient_history(
                            tenant_id=item["tenant_id"],
                            patient_id=item["patient_id"],
                            limit=10,
                        )
                    except Exception as e:
                        logger.warning(f"Could not fetch patient history for note email: {e}")

                if score >= settings.threshold_urgent:
                    await self.notification_service.send_urgent_alert(
                        recipient=settings.clinical_notification_email,
                        report_id=f"NOTE-{item['note_id']}",
                        patient_id=item["patient_id"],
                        score=score,
                        summary=result.summary,
                        findings=[],
                        recommendations=result.recommendations if hasattr(result, 'recommendations') else [],
                        patient_history=patient_history,
                        mongodb_client=self.mongodb_client,
                        tenant_id=item["tenant_id"],
                    )
                    logger.warning(f"URGENT note alert sent for {item['note_id']}")
                elif score >= settings.threshold_important:
                    await self.notification_service.send_important_notification(
                        recipient=settings.clinical_notification_email,
                        report_id=f"NOTE-{item['note_id']}",
                        patient_id=item["patient_id"],
                        score=score,
                        summary=result.summary,
                        patient_history=patient_history,
                        mongodb_client=self.mongodb_client,
                        tenant_id=item["tenant_id"],
                    )
                    logger.info(f"Important note notification sent for {item['note_id']}")
            except Exception as e:
                logger.error(f"Failed to send note notification: {e}")
        
        logger.info(f"Note {item['note_id']}: score={score}")


async def main():
    """Main entry point for worker pod."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    concurrency = int(settings.worker_concurrency or 1)
    worker = PipelineWorker(concurrency=concurrency)
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def shutdown_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(worker.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_handler)
    
    try:
        await worker.start()
        
        # Keep running until stopped
        while worker._running:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
        sys.exit(1)
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
