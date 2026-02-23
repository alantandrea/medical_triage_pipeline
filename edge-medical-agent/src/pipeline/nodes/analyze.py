"""
Step 6: AI Analysis - Comprehensive analysis using MedGemma models.

RADIOLOGY WORKFLOW (Two-Stage):
1. MedGemma 4B (multimodal) analyzes the image → textual findings
2. MedGemma 27B (text-only) synthesizes findings with context → clinical assessment

TEXT-ONLY WORKFLOW (Labs, Pathology):
- MedGemma 27B directly analyzes the extracted text
"""
import logging
import time
from typing import Any
import uuid

from ..state import PipelineState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword-based extraction of body_region and finding_type from free text
# ---------------------------------------------------------------------------
_BODY_REGION_KEYWORDS = {
    "brain": ["brain", "cerebr", "intracranial", "cranial", "cortical", "ventricle", "meningeal"],
    "arteries": ["arteri", "vascular", "aorta", "aneurysm", "dissection",
                  "arteriovenous", "avm", "stenosis", "occlusion", "thrombosis", "embolism",
                  "endarterectomy", "iliac", "femoral artery", "subclavian", "carotid"],
    "nerves": ["cauda equina", "spinal cord", "myelopath", "radiculopath", "neuropath",
               "nerve root", "nerve compress", "guillain", "demyelinat", "neuritis",
               "plexopath", "sciatic", "paresthes", "paraplegia", "quadriplegia",
               "cord compress", "syringomyelia", "motor neuron"],
    "lungs": ["lung", "pulmonary", "pleural", "bronch", "thoracic", "chest", "pneumo", "alveolar"],
    "heart": ["heart", "cardiac", "coronary", "myocardial", "pericardial", "aortic", "atrial", "ventricular"],
    "liver": ["liver", "hepatic", "biliary", "gallbladder", "abdominal"],
    "kidney": ["kidney", "renal", "ureter", "bladder", "pelvic"],
    "spine": ["spine", "spinal", "vertebr", "lumbar", "cervical", "thoracic spine", "disc"],
    "bone": ["bone", "fracture", "skeletal", "femur", "tibia", "rib", "extremity", "joint"],
    "thyroid": ["thyroid", "neck", "cervical mass"],
    "pancreas": ["pancrea"],
    "immune": ["infection", "abscess", "septic", "osteomyelitis", "empyema",
               "cellulitis", "tuberculosis", "meningitis"],
    "reproductive": ["ovari", "uterine", "uterus", "cervical cancer", "endometri",
                      "prostat", "testicular", "testes", "scrotal", "penile",
                      "fallopian", "vaginal", "vulvar", "mammary", "breast"],
    "endocrine": ["adrenal", "pheochromocytoma", "pituitary", "adenoma pituitary",
                   "cushing", "addison", "hyperaldosteronism", "carcinoid",
                   "neuroendocrine", "paraganglioma"],
    "gi": ["stomach", "gastric", "colon", "colonic", "intestin", "bowel",
           "esophag", "rectal", "rectum", "appendix", "duoden", "jejun",
           "ileum", "cecum", "sigmoid", "peritoneal", "mesenteric"],
    "skin": ["skin", "dermal", "subcutaneous", "cutaneous", "melanoma",
             "basal cell", "squamous cell skin", "wound", "ulcer skin"],
    "urinary": ["bladder", "urethra", "ureter", "urinary", "cystitis",
                "urethritis", "vesic"],
    "rheumatology": ["synovial", "synovitis", "arthritis", "gout",
                      "rheumatoid", "lupus", "spondyl", "sacroiliac"],
}

_FINDING_TYPE_KEYWORDS = {
    "hemorrhage": ["hemorrhage", "haemorrhage", "bleed", "hematoma"],
    "mass": ["mass", "tumor", "tumour", "neoplasm", "lesion", "nodule", "growth"],
    "fracture": ["fracture", "broken", "crack"],
    "pneumothorax": ["pneumothorax", "collapsed lung"],
    "effusion": ["effusion", "fluid collection"],
    "infarction": ["infarct", "ischemi", "ischaemi", "stroke"],
    "infection": ["infection", "abscess", "septic", "osteomyelitis", "empyema",
                  "cellulitis", "tuberculosis", "meningitis"],
    "inflammation": ["inflam", "itis"],
    "aneurysm": ["aneurysm", "aneurism"],
    "dissection": ["dissection"],
    "avm": ["arteriovenous malformation", "avm"],
    "stenosis": ["stenosis", "stenotic", "narrowing"],
    "occlusion": ["occlusion", "occluded", "thrombosis", "embolism", "emboli"],
    "cauda_equina": ["cauda equina"],
    "myelopathy": ["myelopath", "cord compress", "spinal cord"],
    "radiculopathy": ["radiculopath", "nerve root", "nerve compress"],
    "neuropathy": ["neuropath", "neuritis", "demyelinat", "guillain", "plexopath"],
    "pheochromocytoma": ["pheochromocytoma", "paraganglioma"],
    "adenoma": ["adenoma", "hyperplasia"],
}


def _extract_body_region(finding_text: str, report_type: str) -> str:
    """Extract body region from finding text, falling back to report type mapping."""
    text_lower = finding_text.lower()
    for region, keywords in _BODY_REGION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return region
    # Fallback: map report type to a default region
    type_map = {"ct": "brain", "mri": "brain", "xray": "lungs", "mra": "brain", "pet": "lungs"}
    return type_map.get(report_type, report_type)


def _extract_finding_type(finding_text: str) -> str:
    """Extract finding type from finding text."""
    text_lower = finding_text.lower()
    for ftype, keywords in _FINDING_TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return ftype
    return "finding"


async def analyze_node(
    state: PipelineState,
    medgemma_27b: Any,
    medgemma_4b: Any = None,
    mongodb_client: Any = None,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Perform comprehensive AI analysis using MedGemma models.
    
    For radiology (xray, ct, mri, mra, pet):
        Stage 1: MedGemma 4B analyzes image → textual findings
        Stage 2: MedGemma 27B synthesizes findings → clinical assessment
    
    For text-only (labs, pathology):
        MedGemma 27B directly analyzes extracted text
    
    Inputs:
        - extracted_text, classified_type
        - patient_context, historical_context
        - image_bytes, image_format (for radiology)
    
    Outputs:
        - analysis_summary
        - findings: List of finding dicts
        - urgency_score (0-100)
        - recommendations
        - image_findings (for radiology - intermediate 4B output)
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    
    logger.info(f"[{tenant_id}] Analyze: Running AI analysis for {report_id}")
    
    try:
        classified_type = state.get("classified_type", "other")
        
        # Determine analysis type
        if classified_type in ["xray", "ct", "mri", "mra", "pet"]:
            # RADIOLOGY: Two-stage analysis
            result = await _analyze_radiology_two_stage(
                state=state,
                medgemma_4b=medgemma_4b,
                medgemma_27b=medgemma_27b,
                mongodb_client=mongodb_client,
                tenant_id=tenant_id
            )
        elif state.get("extracted_text"):
            # TEXT-ONLY: Lab/pathology analysis
            result = await medgemma_27b.analyze_lab_report(
                report_text=state["extracted_text"],
                patient_context=state.get("patient_context"),
                historical_context=state.get("historical_context")
            )
        else:
            # No content to analyze
            logger.warning(f"[{tenant_id}] No content available for analysis")
            state["analysis_summary"] = "No content available for analysis"
            state["findings"] = []
            state["urgency_score"] = 0
            state["recommendations"] = []
            return state
        
        # Store results
        state["analysis_summary"] = result.summary
        state["urgency_score"] = result.urgency_score
        state["recommendations"] = result.recommendations
        
        # Convert findings to structured format
        findings = []
        for i, finding_text in enumerate(result.findings):
            findings.append({
                "finding_id": f"{report_id}-{i+1}",
                "finding_notation": finding_text,
                "urgency_score": result.urgency_score,  # Inherit overall score
            })
        state["findings"] = findings
        
        logger.info(f"[{tenant_id}] Analysis: score={result.urgency_score}, findings={len(findings)}")
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["analyze"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            is_radiology = classified_type in ["xray", "ct", "mri", "mra", "pet"]
            used_4b = bool(state.get("image_findings"))
            await pipeline_logger.log_step(
                state=state, step="analyze", duration_ms=duration_ms,
                synopsis=f"AI analysis: urgency={result.urgency_score}, {len(findings)} findings, "
                         f"{'two-stage (4B+27B)' if used_4b else '27B text-only'}",
                details={
                    "urgency_score": result.urgency_score,
                    "finding_count": len(findings),
                    "model_flow": "4B_image+27B_synthesis" if used_4b else "27B_text_only",
                    "summary_preview": (result.summary or "")[:200],
                    "recommendations": result.recommendations[:3] if result.recommendations else [],
                    "image_abnormalities": state.get("image_abnormalities", False),
                },
            )
        
        logger.info(f"[{tenant_id}] Analyze complete: {duration_ms}ms")
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Analyze failed: {e}")
        state.setdefault("errors", []).append(f"Analyze: {str(e)}")
        state["analysis_summary"] = "Analysis failed — escalated for manual review"
        state["findings"] = []
        state["urgency_score"] = 85  # Escalate on failure — patient safety first
        state["analysis_failed"] = True
        state["recommendations"] = ["URGENT: Manual review required — AI analysis failed, escalated as precaution"]
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="analyze", error=str(e),
                synopsis=f"AI analysis failed, escalated urgency to 85 (safety default): {e}",
            )
    
    return state


async def _analyze_radiology_two_stage(
    state: PipelineState,
    medgemma_4b: Any,
    medgemma_27b: Any,
    mongodb_client: Any,
    tenant_id: str
) -> Any:
    """
    Two-stage radiology analysis:
    1. MedGemma 4B analyzes image → textual findings
    2. Extract structured measurements and store in MongoDB
    3. MedGemma 27B synthesizes findings → clinical assessment
    
    Falls back to text-only if no image available.
    """
    classified_type = state.get("classified_type", "other")
    image_bytes = state.get("image_bytes")
    image_format = state.get("image_format")
    extracted_text = state.get("extracted_text")
    patient_context = state.get("patient_context")
    patient_id = state.get("patient_id")
    report_date_str = state.get("report_date")
    
    # Stage 1: Image analysis with 4B (if image available)
    image_findings = None
    if image_bytes and image_format and medgemma_4b:
        logger.info(f"[{tenant_id}] Stage 1: Analyzing image with MedGemma 4B")
        try:
            image_result = await medgemma_4b.analyze_radiology_image(
                image_bytes=image_bytes,
                image_format=image_format,
                report_type=classified_type,
                clinical_context=patient_context
            )
            image_findings = image_result.findings
            
            # Store intermediate findings for debugging/logging
            state["image_findings"] = image_findings
            state["image_observations"] = image_result.observations
            state["image_abnormalities"] = image_result.abnormalities_detected
            
            logger.info(f"[{tenant_id}] 4B findings: abnormalities={image_result.abnormalities_detected}")
            
            # Stage 1.5: Extract structured measurements and store in MongoDB
            if image_result.abnormalities_detected and mongodb_client:
                try:
                    measurements = await medgemma_4b.extract_radiology_measurements(
                        findings_text=image_findings,
                        report_type=classified_type
                    )
                    
                    from datetime import datetime, timezone
                    report_date = datetime.now(timezone.utc)
                    if report_date_str:
                        try:
                            report_date = datetime.fromisoformat(str(report_date_str).replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass
                    
                    stored_count = 0
                    for m in measurements:
                        await mongodb_client.store_radiology_finding(
                            tenant_id=tenant_id,
                            patient_id=patient_id,
                            finding_type=m.finding_type,
                            body_region=m.body_region,
                            size_mm=m.size_mm,
                            report_date=report_date,
                            notes=m.description
                        )
                        stored_count += 1
                    
                    state["radiology_measurements"] = [
                        {"finding_type": m.finding_type, "body_region": m.body_region,
                         "size_mm": m.size_mm, "description": m.description}
                        for m in measurements
                    ]
                    
                    if stored_count:
                        logger.info(f"[{tenant_id}] Stored {stored_count} radiology measurements in MongoDB")
                except Exception as e:
                    logger.warning(f"[{tenant_id}] Failed to extract/store radiology measurements: {e}")
            
        except Exception as e:
            logger.warning(f"[{tenant_id}] 4B image analysis failed, falling back to text: {e}")
            image_findings = None
    else:
        logger.info(f"[{tenant_id}] No image available, using text-only analysis")
    
    # Stage 2: Synthesis with 27B
    if image_findings:
        # Full two-stage: synthesize image findings with context
        logger.info(f"[{tenant_id}] Stage 2: Synthesizing findings with MedGemma 27B")
        result = await medgemma_27b.synthesize_radiology_findings(
            image_findings=image_findings,
            report_type=classified_type,
            pdf_text=extracted_text,
            patient_context=patient_context
        )
    elif extracted_text:
        # Fallback: text-only analysis of radiology report (radiology-specific prompt)
        logger.info(f"[{tenant_id}] Fallback: Text-only radiology analysis with 27B")
        result = await medgemma_27b.analyze_radiology_text(
            report_text=extracted_text,
            report_type=classified_type,
            patient_context=patient_context
        )
    else:
        # No content at all
        raise ValueError("No image or text content available for radiology analysis")
    
    # Always persist 27B text-based findings to radiology_findings collection
    if mongodb_client and result.findings:
        try:
            from datetime import datetime, timezone
            report_date = datetime.now(timezone.utc)
            if report_date_str:
                try:
                    report_date = datetime.fromisoformat(str(report_date_str).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            
            stored_count = 0
            for finding_text in result.findings:
                await mongodb_client.store_radiology_finding(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    finding_type=_extract_finding_type(finding_text),
                    body_region=_extract_body_region(finding_text, classified_type),
                    size_mm=0.0,
                    report_date=report_date,
                    notes=finding_text
                )
                stored_count += 1
            
            if stored_count:
                logger.info(f"[{tenant_id}] Stored {stored_count} 27B radiology findings in MongoDB")
        except Exception as e:
            logger.warning(f"[{tenant_id}] Failed to store 27B radiology findings: {e}")
    
    return result
