"""
MedGemma Triage System - Main FastAPI Application

Entry point for the medical report triage system.
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.clients import (
    AWSAPIClient,
    MongoDBClient,
    RedisClient,
    MedGemma27BClient,
    MedGemma4BClient,
    LOINCClient,
    PipelineLogger,
)
from src.jobs import PatientSyncJob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [tenant:%(tenant_id)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Add tenant_id to all log records
old_factory = logging.getLogRecordFactory()

def record_factory(*args, **kwargs):
    record = old_factory(*args, **kwargs)
    record.tenant_id = settings.tenant_id
    return record

logging.setLogRecordFactory(record_factory)

logger = logging.getLogger(__name__)


# Global client instances
class AppState:
    aws_client: Optional[AWSAPIClient] = None
    mongodb_client: Optional[MongoDBClient] = None
    redis_client: Optional[RedisClient] = None
    medgemma_27b: Optional[MedGemma27BClient] = None
    medgemma_4b: Optional[MedGemma4BClient] = None
    loinc_client: Optional[LOINCClient] = None
    pipeline_logger: Optional[PipelineLogger] = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info(f"Starting MedGemma Triage System for tenant: {settings.tenant_id}")
    
    # Initialize clients
    state.aws_client = AWSAPIClient()
    
    state.mongodb_client = MongoDBClient()
    await state.mongodb_client.connect()
    
    state.redis_client = RedisClient()
    await state.redis_client.connect()
    
    state.medgemma_27b = MedGemma27BClient()
    state.medgemma_4b = MedGemma4BClient()
    
    # Initialize LOINC client with Redis
    state.loinc_client = LOINCClient(
        state.redis_client.client,
        settings.tenant_id
    )
    
    # Initialize OpenSearch pipeline logger
    state.pipeline_logger = PipelineLogger()
    await state.pipeline_logger.connect()
    
    # LOINC data presence check
    try:
        loinc_meta = await state.loinc_client.get_metadata()
        total_codes = loinc_meta.get("total_codes", 0) if loinc_meta else 0
        if not total_codes:
            logger.warning(
                "No LOINC mappings found in Redis. Lab value LOINC mapping will not work. "
                "Run the LOINC loader to populate data."
            )
        else:
            logger.info(f"LOINC data loaded: {total_codes} codes available")
    except Exception as e:
        logger.warning(f"Could not check LOINC data presence: {e}")
    
    logger.info("All clients initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    if state.pipeline_logger:
        await state.pipeline_logger.close()
    if state.aws_client:
        await state.aws_client.close()
    if state.mongodb_client:
        await state.mongodb_client.close()
    if state.redis_client:
        await state.redis_client.close()
    if state.medgemma_27b:
        await state.medgemma_27b.close()
    if state.medgemma_4b:
        await state.medgemma_4b.close()
    
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="MedGemma Triage System",
    description="AI-powered medical report triage using MedGemma models",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Health Endpoints ====================

@app.get("/health")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "tenant_id": settings.tenant_id}


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check of all dependencies."""
    checks = {
        "tenant_id": settings.tenant_id,
        "aws_api": False,
        "mongodb": False,
        "redis": False,
        "opensearch": False,
        "medgemma_27b": False,
        "medgemma_4b": False,
    }
    
    if state.aws_client:
        checks["aws_api"] = await state.aws_client.health_check()
    
    if state.mongodb_client:
        checks["mongodb"] = await state.mongodb_client.health_check()
    
    if state.redis_client:
        checks["redis"] = await state.redis_client.health_check()
    
    if state.pipeline_logger:
        checks["opensearch"] = await state.pipeline_logger.health_check()
    
    if state.medgemma_27b:
        checks["medgemma_27b"] = await state.medgemma_27b.health_check()
    
    if state.medgemma_4b:
        checks["medgemma_4b"] = await state.medgemma_4b.health_check()
    
    # DLQ depth monitoring
    dlq_info = {"report_dlq": 0, "note_dlq": 0}
    if state.redis_client:
        try:
            dlq_info["report_dlq"] = await state.redis_client.client.llen("medgemma:report_dlq")
            dlq_info["note_dlq"] = await state.redis_client.client.llen("medgemma:note_dlq")
        except Exception:
            pass
    checks["dlq"] = dlq_info
    
    all_healthy = all(
        v for k, v in checks.items()
        if k not in ("tenant_id", "dlq")
    )
    checks["status"] = "healthy" if all_healthy else "degraded"
    
    return checks


# ==================== Patient Sync Endpoints ====================

@app.post("/jobs/patient-sync/full")
async def run_full_patient_sync():
    """Trigger a full patient sync from AWS to MongoDB."""
    job = PatientSyncJob(
        aws_client=state.aws_client,
        mongodb_client=state.mongodb_client,
        redis_client=state.redis_client,
        tenant_id=settings.tenant_id
    )
    result = await job.run_full_sync()
    return result


@app.post("/jobs/patient-sync/incremental")
async def run_incremental_patient_sync():
    """Trigger an incremental patient sync."""
    job = PatientSyncJob(
        aws_client=state.aws_client,
        mongodb_client=state.mongodb_client,
        redis_client=state.redis_client,
        tenant_id=settings.tenant_id
    )
    result = await job.run_incremental_sync()
    return result


@app.get("/jobs/patient-sync/status")
async def get_patient_sync_status():
    """Get patient sync status and statistics."""
    job = PatientSyncJob(
        aws_client=state.aws_client,
        mongodb_client=state.mongodb_client,
        redis_client=state.redis_client,
        tenant_id=settings.tenant_id
    )
    return await job.get_status()


# ==================== DLQ Endpoints ====================

@app.get("/dlq/status")
async def dlq_status():
    """Get dead-letter queue depths."""
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not connected")
    
    report_depth = await state.redis_client.client.llen("medgemma:report_dlq")
    note_depth = await state.redis_client.client.llen("medgemma:note_dlq")
    
    return {
        "report_dlq_depth": report_depth,
        "note_dlq_depth": note_depth,
        "total": report_depth + note_depth,
    }


@app.post("/dlq/redrive/{queue_type}")
async def redrive_dlq(queue_type: str, count: int = 10):
    """
    Move items from DLQ back to the main processing queue for retry.
    
    Args:
        queue_type: 'report' or 'note'
        count: Number of items to redrive (default 10)
    """
    if queue_type not in ("report", "note"):
        raise HTTPException(status_code=400, detail="queue_type must be 'report' or 'note'")
    
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not connected")
    
    dlq_key = f"medgemma:{queue_type}_dlq"
    main_key = f"medgemma:{queue_type}_queue"
    
    redriven = 0
    for _ in range(count):
        item_raw = await state.redis_client.client.rpop(dlq_key)
        if not item_raw:
            break
        
        # Reset retry count before re-queuing
        item = json.loads(item_raw)
        item["retry_count"] = 0
        item.pop("last_error", None)
        item.pop("dead_lettered_at", None)
        
        await state.redis_client.client.lpush(main_key, json.dumps(item))
        redriven += 1
    
    remaining = await state.redis_client.client.llen(dlq_key)
    
    return {
        "redriven": redriven,
        "remaining_in_dlq": remaining,
        "queue_type": queue_type,
    }


@app.get("/dlq/peek/{queue_type}")
async def peek_dlq(queue_type: str, count: int = 5):
    """
    Peek at items in the DLQ without removing them.
    
    Args:
        queue_type: 'report' or 'note'
        count: Number of items to peek (default 5)
    """
    if queue_type not in ("report", "note"):
        raise HTTPException(status_code=400, detail="queue_type must be 'report' or 'note'")
    
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not connected")
    
    dlq_key = f"medgemma:{queue_type}_dlq"
    
    # LRANGE returns items from head; DLQ uses LPUSH so newest are at head
    items_raw = await state.redis_client.client.lrange(dlq_key, 0, count - 1)
    items = [json.loads(item) for item in items_raw]
    
    return {
        "queue_type": queue_type,
        "count": len(items),
        "items": items,
    }


# ==================== LOINC Endpoints ====================

@app.get("/loinc/lookup/code/{loinc_num}")
async def lookup_loinc_by_code(loinc_num: str):
    """Look up a LOINC code by number."""
    if not state.loinc_client:
        raise HTTPException(status_code=503, detail="LOINC client not initialized")
    
    result = await state.loinc_client.lookup_by_code(loinc_num)
    return result.model_dump()


@app.get("/loinc/lookup/name/{test_name}")
async def lookup_loinc_by_name(test_name: str):
    """Look up a LOINC code by test name."""
    if not state.loinc_client:
        raise HTTPException(status_code=503, detail="LOINC client not initialized")
    
    result = await state.loinc_client.lookup_by_name(test_name)
    return result.model_dump()


@app.get("/loinc/search")
async def search_loinc(query: str, limit: int = 10):
    """Search for LOINC codes."""
    if not state.loinc_client:
        raise HTTPException(status_code=503, detail="LOINC client not initialized")
    
    results = await state.loinc_client.search(query, limit)
    return [r.model_dump() for r in results]


@app.get("/loinc/metadata")
async def get_loinc_metadata():
    """Get LOINC data metadata."""
    if not state.loinc_client:
        raise HTTPException(status_code=503, detail="LOINC client not initialized")
    
    return await state.loinc_client.get_metadata()


# ==================== Patient Endpoints ====================

@app.get("/patients/{patient_id}")
async def get_patient(patient_id: int):
    """Get patient by ID from local MongoDB."""
    if not state.mongodb_client:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    patient = await state.mongodb_client.get_patient(settings.tenant_id, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    return patient.model_dump()


@app.get("/patients/{patient_id}/lab-history")
async def get_patient_lab_history(
    patient_id: int,
    loinc_code: Optional[str] = None,
    test_name: Optional[str] = None,
    limit: int = 10
):
    """Get patient's lab value history."""
    if not state.mongodb_client:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    history = await state.mongodb_client.get_patient_lab_history(
        settings.tenant_id,
        patient_id,
        loinc_code=loinc_code,
        test_name=test_name,
        limit=limit
    )
    
    return [h.model_dump() for h in history]


# ==================== Main Entry Point ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
