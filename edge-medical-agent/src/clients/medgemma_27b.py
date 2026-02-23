"""
MedGemma 27B model client for comprehensive medical analysis.
Connects to DGX Spark server at port 8357.

IMPORTANT: MedGemma 27B IT is TEXT-ONLY. It does NOT support images.
For radiology images, use MedGemma 4B (with MedSigLIP) to analyze the image first,
then pass the textual findings to 27B for synthesis.
"""
import httpx
import logging
from typing import Optional, List
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class AnalysisResult(BaseModel):
    """Result from MedGemma 27B analysis."""
    summary: str
    findings: List[str]
    urgency_score: int  # 0-100
    recommendations: List[str]
    raw_response: str


class MedGemma27BClient:
    """
    Client for MedGemma 27B IT model (TEXT-ONLY).
    
    This model handles:
    - Lab report analysis (text)
    - Pathology report analysis (text)
    - Synthesis of radiology findings from 4B model (text)
    
    NOTE: This model does NOT support images. For radiology images,
    use MedGemma4BClient.analyze_radiology_image() first, then pass
    the textual findings to this client for synthesis.
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: float = 300.0):
        self.base_url = base_url or settings.medgemma_27b_url
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def analyze_lab_report(
        self,
        report_text: str,
        patient_context: Optional[str] = None,
        historical_context: Optional[str] = None
    ) -> AnalysisResult:
        """
        Analyze a lab report for clinical significance.
        
        Args:
            report_text: Extracted text from lab report PDF
            patient_context: Patient demographics and history
            historical_context: Previous lab values for trend analysis
        """
        prompt = self._build_lab_prompt(report_text, patient_context, historical_context)
        
        response = await self._generate(prompt)
        return self._parse_analysis_response(response)
    
    async def synthesize_radiology_findings(
        self,
        image_findings: str,
        report_type: str,
        pdf_text: Optional[str] = None,
        patient_context: Optional[str] = None
    ) -> AnalysisResult:
        """
        Synthesize radiology findings from 4B model into clinical assessment.
        
        This is the second stage of radiology analysis:
        1. MedGemma 4B analyzes the image → textual findings
        2. MedGemma 27B synthesizes findings with context → clinical assessment
        
        Args:
            image_findings: Textual findings from MedGemma 4B image analysis
            report_type: Type of imaging study (xray, ct, mri, mra, pet)
            pdf_text: Optional text from radiology report PDF
            patient_context: Patient demographics and history
        """
        prompt = self._build_radiology_synthesis_prompt(
            image_findings, report_type, pdf_text, patient_context
        )
        
        response = await self._generate(prompt)
        return self._parse_analysis_response(response)

    async def analyze_radiology_text(
        self,
        report_text: str,
        report_type: str,
        patient_context: Optional[str] = None
    ) -> AnalysisResult:
        """
        Analyze a radiology report from text only (no image available).
        
        Uses a radiology-specific prompt instead of the lab prompt,
        so findings are framed correctly for imaging studies.
        
        Args:
            report_text: Extracted text from radiology report PDF
            report_type: Type of imaging study (xray, ct, mri, mra, pet)
            patient_context: Patient demographics and history
        """
        prompt = self._build_radiology_text_prompt(
            report_text, report_type, patient_context
        )
        response = await self._generate(prompt)
        return self._parse_analysis_response(response)

    async def _generate(self, prompt: str) -> str:
        """Send text-only generation request via OpenAI-compatible chat completions API."""
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": "medgemma-27b",
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                }
            )
            response.raise_for_status()
            data = response.json()
            # OpenAI format: choices[0].message.content
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        except httpx.HTTPError as e:
            logger.error(f"MedGemma 27B generation failed: {e}")
            raise
    
    def _build_lab_prompt(
        self,
        report_text: str,
        patient_context: Optional[str],
        historical_context: Optional[str]
    ) -> str:
        """Build prompt for lab report analysis."""
        prompt = """You are a clinical decision support system analyzing lab results.

Analyze the following lab report and provide:
1. A brief clinical summary
2. Key findings that require attention
3. An urgency score from 0-100 (0=routine, 100=critical)
4. Recommended next steps

"""
        if patient_context:
            prompt += f"Patient Context:\n{patient_context}\n\n"
        
        if historical_context:
            prompt += f"Historical Lab Values:\n{historical_context}\n\n"
        
        prompt += f"Lab Report:\n{report_text}\n\n"
        prompt += """Respond in this exact format:
SUMMARY: [brief clinical summary]
FINDINGS:
- [finding 1]
- [finding 2]
URGENCY_SCORE: [0-100]
RECOMMENDATIONS:
- [recommendation 1]
- [recommendation 2]"""
        
        return prompt

    def _build_radiology_synthesis_prompt(
        self,
        image_findings: str,
        report_type: str,
        pdf_text: Optional[str],
        patient_context: Optional[str]
    ) -> str:
        """Build prompt for synthesizing radiology findings."""
        modality_map = {
            "xray": "X-ray",
            "ct": "CT scan",
            "mri": "MRI",
            "mra": "MR Angiography",
            "pet": "PET scan"
        }
        modality = modality_map.get(report_type, report_type.upper())
        
        prompt = f"""You are a clinical decision support system synthesizing {modality} findings.

An AI image analysis system has examined the {modality} and produced the following findings:

IMAGE ANALYSIS FINDINGS:
{image_findings}

"""
        if pdf_text:
            prompt += f"RADIOLOGY REPORT TEXT:\n{pdf_text}\n\n"
        
        if patient_context:
            prompt += f"PATIENT CONTEXT:\n{patient_context}\n\n"
        
        prompt += """Based on the image analysis findings and available context, provide:
1. A clinical summary integrating all findings
2. Key findings that require clinical attention
3. An urgency score from 0-100 (0=routine, 100=critical)
4. Recommended follow-up actions

Respond in this exact format:
SUMMARY: [clinical summary integrating findings]
FINDINGS:
- [finding 1]
- [finding 2]
URGENCY_SCORE: [0-100]
RECOMMENDATIONS:
- [recommendation 1]
- [recommendation 2]"""
        
        return prompt

    def _build_radiology_text_prompt(
        self,
        report_text: str,
        report_type: str,
        patient_context: Optional[str]
    ) -> str:
        """Build prompt for text-only radiology report analysis (no image available)."""
        modality_map = {
            "xray": "X-ray",
            "ct": "CT scan",
            "mri": "MRI",
            "mra": "MR Angiography",
            "pet": "PET scan"
        }
        modality = modality_map.get(report_type, report_type.upper())

        prompt = f"""You are a clinical decision support system analyzing a {modality} radiology report.
No image is available for this study. Analyze the radiology report text below, focusing on:
- Reported findings and their clinical significance
- Any abnormalities or interval changes noted by the radiologist
- Impression and recommendations from the report

"""
        if patient_context:
            prompt += f"PATIENT CONTEXT:\n{patient_context}\n\n"

        prompt += f"RADIOLOGY REPORT:\n{report_text}\n\n"
        prompt += """Provide:
1. A clinical summary of the radiology findings
2. Key findings that require clinical attention
3. An urgency score from 0-100 (0=routine, 100=critical)
4. Recommended follow-up actions

Respond in this exact format:
SUMMARY: [clinical summary of radiology findings]
FINDINGS:
- [finding 1]
- [finding 2]
URGENCY_SCORE: [0-100]
RECOMMENDATIONS:
- [recommendation 1]
- [recommendation 2]"""

        return prompt

    def _parse_analysis_response(self, response: str) -> AnalysisResult:
        """Parse structured response from model."""
        summary = ""
        findings = []
        urgency_score = 0
        recommendations = []
        
        lines = response.strip().split("\n")
        current_section = None
        
        for line in lines:
            line = line.strip()
            if line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
                current_section = None
            elif line.startswith("FINDINGS:"):
                current_section = "findings"
            elif line.startswith("URGENCY_SCORE:"):
                try:
                    score_str = line.replace("URGENCY_SCORE:", "").strip()
                    urgency_score = int(score_str)
                except ValueError:
                    urgency_score = 50  # Default to moderate if parsing fails
                current_section = None
            elif line.startswith("RECOMMENDATIONS:"):
                current_section = "recommendations"
            elif line.startswith("- ") and current_section:
                item = line[2:].strip()
                if current_section == "findings":
                    findings.append(item)
                elif current_section == "recommendations":
                    recommendations.append(item)
        
        return AnalysisResult(
            summary=summary or "Analysis completed",
            findings=findings,
            urgency_score=max(0, min(100, urgency_score)),
            recommendations=recommendations,
            raw_response=response
        )
    
    async def health_check(self) -> bool:
        """Check if MedGemma 27B server is reachable."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def classify_report_type(self, report_text: str) -> str:
        """
        Classify the type of medical report.
        
        MedGemma 27B handles all text classification and routing decisions.
        
        Returns: lab, xray, ct, mri, mra, pet, path, other
        """
        prompt = f"""Classify this medical report into one of these categories:
- lab (laboratory test results)
- xray (X-ray imaging)
- ct (CT scan)
- mri (MRI scan)
- mra (MRA scan)
- pet (PET scan)
- path (pathology report)
- other

Report text:
{report_text[:2000]}

Respond with only the category name, nothing else."""
        
        response = await self._generate(prompt)
        category = response.strip().lower()
        
        valid_categories = ["lab", "xray", "ct", "mri", "mra", "pet", "path", "other"]
        return category if category in valid_categories else "other"

    async def extract_lab_values(self, report_text: str) -> 'ExtractionResult':
        """
        Extract structured lab values from report text.
        
        MedGemma 27B handles all text extraction and analysis.
        
        Args:
            report_text: Raw text from lab report PDF
        """
        from .medgemma_4b import ExtractionResult, ExtractedLabValue
        
        prompt = self._build_extraction_prompt(report_text)
        response = await self._generate(prompt)
        return self._parse_extraction_response(response)

    def _build_extraction_prompt(self, report_text: str) -> str:
        """Build prompt for lab value extraction."""
        return f"""Extract all lab test results from this report. For each test, provide:
- test_name: The name of the test
- value: The numeric or text result
- unit: The unit of measurement
- reference_range: The normal range if shown
- flag: HIGH, LOW, CRITICAL_HIGH, CRITICAL_LOW, or NORMAL

Lab Report:
{report_text}

Respond in this exact format for each test found:
TEST: [test name]
VALUE: [result value]
UNIT: [unit]
RANGE: [reference range or "not specified"]
FLAG: [HIGH/LOW/CRITICAL_HIGH/CRITICAL_LOW/NORMAL]
---"""

    def _parse_extraction_response(self, response: str) -> 'ExtractionResult':
        """Parse structured extraction response."""
        from .medgemma_4b import ExtractionResult, ExtractedLabValue
        
        lab_values = []
        
        # Split by test delimiter
        tests = response.split("---")
        
        for test_block in tests:
            if not test_block.strip():
                continue
            
            test_data = {}
            for line in test_block.strip().split("\n"):
                line = line.strip()
                if line.startswith("TEST:"):
                    test_data["test_name"] = line.replace("TEST:", "").strip()
                elif line.startswith("VALUE:"):
                    test_data["value"] = line.replace("VALUE:", "").strip()
                elif line.startswith("UNIT:"):
                    test_data["unit"] = line.replace("UNIT:", "").strip()
                elif line.startswith("RANGE:"):
                    range_val = line.replace("RANGE:", "").strip()
                    if range_val.lower() != "not specified":
                        test_data["reference_range"] = range_val
                elif line.startswith("FLAG:"):
                    test_data["flag"] = line.replace("FLAG:", "").strip()
            
            if test_data.get("test_name") and test_data.get("value"):
                lab_values.append(ExtractedLabValue(
                    test_name=test_data.get("test_name", ""),
                    value=test_data.get("value", ""),
                    unit=test_data.get("unit", ""),
                    reference_range=test_data.get("reference_range"),
                    flag=test_data.get("flag")
                ))
        
        return ExtractionResult(
            lab_values=lab_values,
            raw_response=response
        )

    # ==================== Tapestry Classification ====================

    TAPESTRY_REGIONS = [
        "brain", "thyroid", "lungs", "heart", "liver", "pancreas", "kidney",
        "spine", "blood", "bone", "arteries", "nerves", "immune",
        "reproductive", "endocrine", "gi", "skin", "urinary",
        "rheumatology", "genomic",
    ]

    async def classify_tapestry_regions(
        self,
        patient_summary: str,
    ) -> dict:
        """
        Ask MedGemma 27B to classify which tapestry body regions are
        affected based on a compiled patient summary.

        Args:
            patient_summary: Pre-built text containing all patient data
                (labs, radiology findings, report findings, notes, history).

        Returns:
            Dict with keys:
                regions: list of dicts, each with:
                    region: str (one of TAPESTRY_REGIONS)
                    severity: "caution" | "abnormal" | "critical"
                    is_mass: bool
                    is_anatomical: bool
                    reason: str (short explanation)
        """
        prompt = self._build_tapestry_prompt(patient_summary)
        raw = await self._generate(prompt)
        return self._parse_tapestry_response(raw)

    def _build_tapestry_prompt(self, patient_summary: str) -> str:
        return f"""You are a clinical decision support system. Your task is to analyze a patient's complete medical data and determine which body systems are affected.

VALID BODY REGIONS AND WHAT THEY COVER:
- "brain": brain, cerebral, intracranial, cranial, neurological conditions affecting the brain
- "thyroid": thyroid gland, TSH/T3/T4 abnormalities
- "lungs": lungs, pulmonary, pleural, bronchial, thoracic, chest, pneumonia, COPD, pulmonary embolism
- "heart": heart, cardiac, coronary, myocardial, pericardial, heart failure, arrhythmia
- "liver": liver, hepatic, biliary, gallbladder, hepatitis, cirrhosis
- "pancreas": pancreas, diabetes, glucose/HbA1c abnormalities, pancreatitis
- "kidney": kidney, renal, ureter, kidney disease, dialysis
- "spine": spine, spinal, vertebral, lumbar, cervical, disc herniation, scoliosis, spinal stenosis
- "blood": blood disorders, lymphoma, leukemia, lymphadenopathy, anemia, myeloma, pancytopenia, abnormal CBC
- "bone": bone, fracture, skeletal, osteoporosis, calcium/vitamin D abnormalities
- "arteries": arteries, vascular, aorta, aneurysm, stenosis, thrombosis, DVT, cholesterol/lipid abnormalities
- "nerves": peripheral nerves, neuropathy, radiculopathy, cauda equina, spinal cord compression
- "immune": immune system, infections, HIV, hepatitis, tuberculosis, autoimmune (ANA, complement)
- "reproductive": reproductive organs, breast, ovarian, uterine, prostate, testicular, cervical, PSA, hormones (estrogen, testosterone, FSH, LH)
- "endocrine": endocrine (non-thyroid), adrenal, pituitary, cortisol, growth hormone, Cushing's
- "gi": gastrointestinal, colon, stomach, intestine, bowel, esophagus, rectal, appendix, Crohn's, colitis, GI bleeding
- "skin": skin, dermal, melanoma, basal cell, wound, dermatitis
- "urinary": urinary tract, bladder, urethra, UTI, urinalysis abnormalities
- "rheumatology": rheumatology, arthritis, gout, lupus, rheumatoid factor, joint inflammation
- "genomic": genomic, pharmacogenomic, BRCA, KRAS, EGFR mutation, HER2, genetic testing

SEVERITY LEVELS:
- "caution": borderline or mildly abnormal findings
- "abnormal": clearly abnormal, needs clinical attention
- "critical": emergency-level, life-threatening, or cancer/malignancy

SPECIAL FLAGS:
- is_mass: true if the finding involves a mass, tumor, cancer, carcinoma, malignancy, neoplasm, lymphoma, leukemia, sarcoma, or melanoma
- is_anatomical: true if the finding involves a fracture, hemorrhage, pneumothorax, aneurysm, dissection, stenosis, occlusion, or thrombosis

PATIENT DATA:
{patient_summary}

INSTRUCTIONS:
1. Analyze ALL the patient data above thoroughly
2. Identify EVERY affected body region — do not miss any condition
3. A single condition can affect MULTIPLE regions (e.g., metastatic cancer affects the primary site AND blood)
4. If a patient has cancer, the relevant region MUST be marked critical with is_mass=true
5. Abnormal lab values should light up the corresponding region
6. Include findings from ALL sources: current report, historical reports, radiology, labs, and clinical notes

Respond ONLY with a JSON array. No other text. Example:
[
  {{"region": "blood", "severity": "critical", "is_mass": true, "is_anatomical": false, "reason": "Lymphoma detected"}},
  {{"region": "lungs", "severity": "abnormal", "is_mass": false, "is_anatomical": true, "reason": "Pleural effusion"}}
]

If no regions are affected, respond with an empty array: []

JSON:"""

    def _parse_tapestry_response(self, raw: str) -> dict:
        """Parse the JSON array from MedGemma's tapestry classification."""
        import json

        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()

        # Find the JSON array in the response
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            logger.warning(f"Tapestry classification: no JSON array found in response")
            return {"regions": []}

        try:
            arr = json.loads(raw[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"Tapestry classification: JSON parse failed: {e}")
            return {"regions": []}

        valid = []
        for item in arr:
            region = (item.get("region") or "").lower().strip()
            if region not in self.TAPESTRY_REGIONS:
                continue
            severity = (item.get("severity") or "").lower().strip()
            if severity not in ("caution", "abnormal", "critical"):
                severity = "caution"
            valid.append({
                "region": region,
                "severity": severity,
                "is_mass": bool(item.get("is_mass", False)),
                "is_anatomical": bool(item.get("is_anatomical", False)),
                "reason": str(item.get("reason", "")),
            })

        return {"regions": valid}

