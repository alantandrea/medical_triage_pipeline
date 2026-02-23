"""
Step 3: Extract - Extract structured data using MedGemma 27B and LOINC mapping.

MedGemma 27B is the primary model for all text analysis including lab value extraction.
MedGemma 4B is ONLY used for radiology image analysis.
"""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from ..state import PipelineState
from ...models import StructuredLabValue

logger = logging.getLogger(__name__)


def _parse_reference_range(range_str: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse a reference range string into (low, high) floats.
    
    Handles formats like:
        "10-40"
        "10 - 40"
        "10-40 U/L"
        "0.5-1.2 mg/dL"
        "<200"
        ">60"
        "< 200 mg/dL"
        "3.5 - 5.0"
    
    Returns (None, None) if unparseable.
    """
    if not range_str:
        return None, None
    
    s = range_str.strip()
    
    # Try "low - high" pattern (with optional units after)
    m = re.match(r'([<>]?\s*[\d.]+)\s*[-–—]\s*([\d.]+)', s)
    if m:
        try:
            low = float(re.sub(r'[<> ]', '', m.group(1)))
            high = float(m.group(2))
            return low, high
        except (ValueError, TypeError):
            pass
    
    # Try "<value" (upper bound only)
    m = re.match(r'<\s*([\d.]+)', s)
    if m:
        try:
            return None, float(m.group(1))
        except (ValueError, TypeError):
            pass
    
    # Try ">value" (lower bound only)
    m = re.match(r'>\s*([\d.]+)', s)
    if m:
        try:
            return float(m.group(1)), None
        except (ValueError, TypeError):
            pass
    
    return None, None


async def extract_node(
    state: PipelineState,
    medgemma_27b: Any,
    loinc_client: Any,
    mongodb_client: Any = None,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Extract structured lab values and map to LOINC codes.
    
    Uses MedGemma 27B for extraction - it handles all text analysis.
    MedGemma 4B is only for radiology images.
    
    Inputs:
        - extracted_text from classify step
        - classified_type
    
    Outputs:
        - extracted_lab_values: List of structured values
        - loinc_mappings: test_name -> loinc_code
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    
    logger.info(f"[{tenant_id}] Extract: Processing report {report_id}")
    
    try:
        extracted_text = state.get("extracted_text", "")
        classified_type = state.get("classified_type", "other")
        
        lab_values = []
        loinc_mappings = {}
        
        # Only extract lab values for lab reports
        if classified_type == "lab" and extracted_text:
            # Use 27B model to extract structured values - it's the primary text analysis model
            result = await medgemma_27b.extract_lab_values(extracted_text)
            
            for lv in result.lab_values:
                lab_dict = {
                    "test_name": lv.test_name,
                    "value": lv.value,
                    "unit": lv.unit,
                    "reference_range": lv.reference_range,
                    "flag": lv.flag,
                }
                
                # Map to LOINC code
                if loinc_client:
                    lookup = await loinc_client.lookup_by_name(lv.test_name)
                    if lookup.found:
                        lab_dict["loinc_code"] = lookup.code.loinc_num
                        loinc_mappings[lv.test_name] = lookup.code.loinc_num
                        logger.debug(f"[{tenant_id}] Mapped {lv.test_name} -> {lookup.code.loinc_num}")
                
                lab_values.append(lab_dict)
            
            logger.info(f"[{tenant_id}] Extracted {len(lab_values)} lab values, {len(loinc_mappings)} LOINC mappings")
        
        state["extracted_lab_values"] = lab_values
        state["loinc_mappings"] = loinc_mappings
        
        # Persist extracted lab values to MongoDB for trend analysis
        if lab_values and mongodb_client:
            try:
                report_date = state.get("report_date") or datetime.now(timezone.utc)
                structured_values = []
                for lv in lab_values:
                    if lv.get("value") is not None:
                        try:
                            numeric_val = float(lv["value"])
                        except (ValueError, TypeError):
                            continue
                        ref_low, ref_high = _parse_reference_range(lv.get("reference_range"))
                        structured_values.append(StructuredLabValue(
                            tenant_id=tenant_id,
                            patient_id=state["patient_id"],
                            report_id=report_id,
                            collection_date=report_date,
                            test_name=lv.get("test_name", ""),
                            loinc_code=lv.get("loinc_code"),
                            value=numeric_val,
                            unit=lv.get("unit", ""),
                            reference_range_low=ref_low,
                            reference_range_high=ref_high,
                            flag=lv.get("flag"),
                            raw_text=f"{lv.get('test_name', '')}: {lv['value']} {lv.get('unit', '')}",
                        ))
                if structured_values:
                    stored = await mongodb_client.store_lab_values_batch(structured_values)
                    logger.info(f"[{tenant_id}] Persisted {stored} lab values to MongoDB")
            except Exception as e:
                logger.warning(f"[{tenant_id}] Failed to persist lab values: {e}")
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["extract"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            test_names = [lv["test_name"] for lv in lab_values[:10]]
            await pipeline_logger.log_step(
                state=state, step="extract", duration_ms=duration_ms,
                synopsis=f"Extracted {len(lab_values)} lab values, {len(loinc_mappings)} LOINC mapped",
                details={"lab_count": len(lab_values), "loinc_mapped": len(loinc_mappings), "tests": test_names},
            )
        
        logger.info(f"[{tenant_id}] Extract complete: {duration_ms}ms")
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Extract failed: {e}")
        state.setdefault("errors", []).append(f"Extract: {str(e)}")
        state["extracted_lab_values"] = []
        state["loinc_mappings"] = {}
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="extract", error=str(e),
                synopsis=f"Extraction failed: {e}",
            )
    
    return state
