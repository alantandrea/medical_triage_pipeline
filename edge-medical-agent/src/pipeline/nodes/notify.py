"""
Step 8: Notify - Send notifications based on priority level.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..state import PipelineState
from ...config import settings

logger = logging.getLogger(__name__)


async def notify_node(
    state: PipelineState,
    notification_service: Any,
    mongodb_client: Any,
    pipeline_logger: Any = None,
    medgemma_27b: Any = None,
) -> PipelineState:
    """
    Send notifications based on priority level and persist results.
    
    Notification rules:
    - urgent: Immediate email to clinical team
    - important: Email notification
    - followup: Queue for daily digest
    - routine: No notification, just persist
    
    Inputs:
        - final_score, priority_level
        - findings, recommendations
        - patient context
    
    Outputs:
        - notification_sent
        - notification_type
        - notification_recipients
        - processing_completed
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    patient_id = state["patient_id"]
    
    logger.info(f"[{tenant_id}] Notify: Processing notifications for {report_id}")
    
    try:
        priority_level = state.get("priority_level", "routine")
        final_score = state.get("final_score", 0)
        
        notification_sent = False
        notification_type = None
        recipients = []
        
        # Fetch patient history for email context (urgent/important only)
        patient_history = []
        if priority_level in ("urgent", "important") and mongodb_client:
            try:
                patient_history = await mongodb_client.get_patient_history(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    exclude_report_id=report_id,
                    limit=10,
                )
            except Exception as e:
                logger.warning(f"[{tenant_id}] Could not fetch patient history: {e}")

        if priority_level == "urgent":
            # Immediate notification
            if notification_service and settings.clinical_notification_email:
                await notification_service.send_urgent_alert(
                    recipient=settings.clinical_notification_email,
                    report_id=report_id,
                    patient_id=patient_id,
                    score=final_score,
                    summary=state.get("analysis_summary", ""),
                    findings=state.get("findings", []),
                    recommendations=state.get("recommendations", []),
                    patient_history=patient_history,
                    mongodb_client=mongodb_client,
                    tenant_id=tenant_id,
                    medgemma_27b=medgemma_27b,
                )
                notification_sent = True
                notification_type = "urgent_email"
                recipients.append(settings.clinical_notification_email)
                logger.warning(f"[{tenant_id}] URGENT alert sent for report {report_id}")
        
        elif priority_level == "important":
            # Standard notification
            if notification_service and settings.clinical_notification_email:
                await notification_service.send_important_notification(
                    recipient=settings.clinical_notification_email,
                    report_id=report_id,
                    patient_id=patient_id,
                    score=final_score,
                    summary=state.get("analysis_summary", ""),
                    patient_history=patient_history,
                    mongodb_client=mongodb_client,
                    tenant_id=tenant_id,
                    medgemma_27b=medgemma_27b,
                )
                notification_sent = True
                notification_type = "important_email"
                recipients.append(settings.clinical_notification_email)
                logger.info(f"[{tenant_id}] Important notification sent for report {report_id}")
        
        elif priority_level == "followup":
            # Queue for digest (just mark, actual digest sent separately)
            notification_type = "digest_queued"
            logger.info(f"[{tenant_id}] Report {report_id} queued for daily digest")
        
        else:
            # Routine - no notification
            notification_type = "none"
        
        state["notification_sent"] = notification_sent
        state["notification_type"] = notification_type
        state["notification_recipients"] = recipients
        state["processing_completed"] = datetime.now(timezone.utc)
        
        # Persist results to MongoDB
        await mongodb_client.mark_report_processed(
            tenant_id=tenant_id,
            report_id=report_id,
            patient_id=patient_id,
            score=final_score,
            findings=[f for f in state.get("findings", [])],
            analysis_summary=state.get("analysis_summary", ""),
        )
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["notify"] = duration_ms
        
        # Log total processing time
        total_ms = None
        if state.get("processing_started"):
            total_ms = int((datetime.now(timezone.utc) - state["processing_started"]).total_seconds() * 1000)
            logger.info(f"[{tenant_id}] Report {report_id} processed: score={final_score}, total_time={total_ms}ms")
        
        # Log to OpenSearch
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="notify", duration_ms=duration_ms,
                synopsis=f"Notified: {priority_level}, notification={notification_type}",
                details={
                    "notification_sent": notification_sent,
                    "notification_type": notification_type,
                    "recipients": recipients,
                    "total_pipeline_ms": total_ms,
                },
            )
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Notify failed: {e}")
        state.setdefault("errors", []).append(f"Notify: {str(e)}")
        state["notification_sent"] = False
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="notify", error=str(e),
                synopsis=f"Notification failed: {e}",
            )
    
    return state
