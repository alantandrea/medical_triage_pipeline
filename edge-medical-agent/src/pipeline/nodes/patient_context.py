"""
Step 4: Patient Context - Fetch patient demographics from MongoDB.
"""
import logging
import time
from typing import Any, Optional

from ..state import PipelineState

logger = logging.getLogger(__name__)


async def patient_context_node(
    state: PipelineState,
    mongodb_client: Any,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Fetch patient demographics to provide context for analysis.
    
    Inputs:
        - patient_id from state
    
    Outputs:
        - patient_name, patient_dob
        - patient_context (formatted string for model)
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    patient_id = state["patient_id"]
    
    logger.info(f"[{tenant_id}] PatientContext: Fetching patient {patient_id}")
    
    try:
        patient = await mongodb_client.get_patient(tenant_id, patient_id)
        
        if patient:
            state["patient_name"] = f"{patient.first_name} {patient.last_name}"
            state["patient_dob"] = patient.patient_dob
            
            # Build context string for model (no PHI in logs!)
            age = _calculate_age(patient.patient_dob)
            context_parts = [
                f"Age: {age} years" if age is not None else "Age: unknown",
                f"Sex: {patient.sex}",
            ]
            state["patient_context"] = ", ".join(context_parts)
            
            logger.info(f"[{tenant_id}] Patient context loaded")
        else:
            logger.warning(f"[{tenant_id}] Patient {patient_id} not found in MongoDB")
            state["patient_context"] = "Patient demographics unavailable"
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["patient_context"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            found = patient is not None
            await pipeline_logger.log_step(
                state=state, step="patient_context", duration_ms=duration_ms,
                synopsis=f"Patient {'found' if found else 'NOT found'}: {state.get('patient_context', '')}",
                details={"patient_found": found, "context": state.get("patient_context", "")},
            )
        
    except Exception as e:
        logger.error(f"[{tenant_id}] PatientContext failed: {e}")
        state.setdefault("errors", []).append(f"PatientContext: {str(e)}")
        state["patient_context"] = "Patient demographics unavailable"
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="patient_context", error=str(e),
                synopsis=f"Patient context failed: {e}",
            )
    
    return state


def _calculate_age(dob_str: str) -> Optional[int]:
    """Calculate age from DOB string (YYYY-MM-DD). Returns None on failure."""
    try:
        from datetime import datetime
        dob = datetime.strptime(dob_str[:10], "%Y-%m-%d")
        today = datetime.today()
        age = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1
        return age
    except Exception:
        return None
