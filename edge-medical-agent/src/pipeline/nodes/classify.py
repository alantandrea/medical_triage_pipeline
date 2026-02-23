"""
Step 2: Classify - Determine report type using MedGemma 27B.

MedGemma 27B is the primary model for all text analysis and routing decisions.
MedGemma 4B is ONLY used for radiology image analysis.
"""
import logging
import time
from typing import Any

from pypdf import PdfReader
import io

from ..state import PipelineState

logger = logging.getLogger(__name__)

# OCR availability flag — graceful degradation if not installed
_OCR_AVAILABLE = False
try:
    from PIL import Image
    from pdf2image import convert_from_bytes
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    logger.info("OCR dependencies (pytesseract/pdf2image/Pillow) not installed — OCR fallback disabled")


async def classify_node(
    state: PipelineState,
    medgemma_27b: Any,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Classify the report type if not already known.
    Extract text from PDF for classification.
    
    Uses MedGemma 27B for classification - it handles all text analysis
    and routing decisions. MedGemma 4B is only for radiology images.
    
    Inputs:
        - pdf_bytes from state
        - report_type (may be pre-classified)
    
    Outputs:
        - classified_type
        - extracted_text (preliminary)
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    
    logger.info(f"[{tenant_id}] Classify: Processing report {report_id}")
    
    try:
        # Extract text from PDF
        extracted_text = ""
        if state.get("pdf_bytes"):
            pdf_reader = PdfReader(io.BytesIO(state["pdf_bytes"]))
            for page in pdf_reader.pages:
                extracted_text += page.extract_text() or ""
            
            if not extracted_text.strip():
                logger.warning(
                    f"[{tenant_id}] PDF text extraction yielded empty text for {report_id}. "
                    f"This may be a scanned/image-based PDF that requires OCR."
                )
                # OCR fallback for scanned PDFs
                if _OCR_AVAILABLE and state.get("pdf_bytes"):
                    try:
                        logger.info(f"[{tenant_id}] Attempting OCR on scanned PDF for {report_id}")
                        images = convert_from_bytes(state["pdf_bytes"])
                        ocr_parts = []
                        for i, img in enumerate(images):
                            page_text = pytesseract.image_to_string(img)
                            if page_text.strip():
                                ocr_parts.append(page_text)
                        extracted_text = "\n".join(ocr_parts)
                        if extracted_text.strip():
                            logger.info(
                                f"[{tenant_id}] OCR extracted {len(extracted_text)} chars "
                                f"from {len(images)} pages"
                            )
                        else:
                            logger.warning(f"[{tenant_id}] OCR also yielded empty text for {report_id}")
                    except Exception as ocr_err:
                        logger.error(f"[{tenant_id}] OCR failed for {report_id}: {ocr_err}")
                elif not _OCR_AVAILABLE:
                    logger.warning(
                        f"[{tenant_id}] OCR dependencies not installed, cannot process scanned PDF"
                    )
            else:
                logger.info(f"[{tenant_id}] Extracted {len(extracted_text)} chars from PDF")
        
        state["extracted_text"] = extracted_text
        
        # Classify if not already known
        report_type = state.get("report_type", "").lower()
        
        if report_type in ["lab", "xray", "ct", "mri", "mra", "pet", "path"]:
            state["classified_type"] = report_type
        elif extracted_text:
            # Use 27B model to classify - it's the primary model for all text analysis
            classified = await medgemma_27b.classify_report_type(extracted_text)
            state["classified_type"] = classified
            logger.info(f"[{tenant_id}] Classified as: {classified}")
        else:
            state["classified_type"] = "other"
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["classify"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            ct = state.get("classified_type", "unknown")
            method = "pre-classified" if report_type in ["lab","xray","ct","mri","mra","pet","path"] else "27B model"
            await pipeline_logger.log_step(
                state=state, step="classify", duration_ms=duration_ms,
                synopsis=f"Classified as '{ct}' via {method}, extracted {len(extracted_text)} chars",
                details={"classified_type": ct, "text_length": len(extracted_text), "method": method},
            )
        
        logger.info(f"[{tenant_id}] Classify complete: {duration_ms}ms")
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Classify failed: {e}")
        state.setdefault("errors", []).append(f"Classify: {str(e)}")
        state["classified_type"] = state.get("report_type", "other")
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="classify", error=str(e),
                synopsis=f"Classification failed, defaulting to '{state['classified_type']}': {e}",
            )
    
    return state
