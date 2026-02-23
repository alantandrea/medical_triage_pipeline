"""
MedGemma 4B model client for radiology image analysis and text extraction.
Connects to DGX Spark server at port 8358.

IMPORTANT: MedGemma 4B (with MedSigLIP) is the ONLY model that handles images.
Use this for radiology image analysis, then pass findings to 27B for synthesis.
"""
import httpx
import logging
import base64
from typing import Optional, List
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class ExtractedLabValue(BaseModel):
    """Single extracted lab value."""
    test_name: str
    value: str
    unit: str
    reference_range: Optional[str] = None
    flag: Optional[str] = None  # HIGH, LOW, CRITICAL, NORMAL


class ExtractionResult(BaseModel):
    """Result from lab value extraction."""
    lab_values: List[ExtractedLabValue]
    report_date: Optional[str] = None
    ordering_provider: Optional[str] = None
    raw_response: str


class ImageAnalysisResult(BaseModel):
    """Result from radiology image analysis."""
    findings: str  # Textual description of findings
    observations: List[str]  # List of specific observations
    abnormalities_detected: bool
    confidence: str  # high, medium, low
    raw_response: str


class StructuredMeasurement(BaseModel):
    """A single structured measurement extracted from radiology findings."""
    finding_type: str  # nodule, mass, effusion, lesion, calcification, etc.
    body_region: str   # lung, liver, brain, kidney, etc.
    size_mm: Optional[float] = None  # Size in millimeters
    description: str = ""  # Brief description


class MedGemma4BClient:
    """
    Client for MedGemma 4B multimodal model (with MedSigLIP).
    
    This model handles:
    - Radiology image analysis (X-ray, CT, MRI, MRA, PET)
    - Fast text extraction and classification
    - Lab value extraction
    
    For radiology workflow:
    1. Use analyze_radiology_image() to get textual findings from image
    2. Pass findings to MedGemma27BClient.synthesize_radiology_findings()
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: float = 90.0):
        self.base_url = base_url or settings.medgemma_4b_url
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def analyze_radiology_image(
        self,
        image_bytes: bytes,
        image_format: str,  # "jpeg" or "png"
        report_type: str,  # xray, ct, mri, mra, pet
        clinical_context: Optional[str] = None
    ) -> ImageAnalysisResult:
        """
        Analyze a radiology image using MedGemma 4B's multimodal capabilities.
        
        This is the FIRST stage of radiology analysis:
        1. MedGemma 4B analyzes the image → textual findings (THIS METHOD)
        2. MedGemma 27B synthesizes findings with context → clinical assessment
        
        Args:
            image_bytes: Raw image data
            image_format: Image format (jpeg/png)
            report_type: Type of imaging study (xray, ct, mri, mra, pet)
            clinical_context: Optional clinical indication and history
        
        Returns:
            ImageAnalysisResult with textual findings to pass to 27B
        """
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = self._build_image_analysis_prompt(report_type, clinical_context)
        
        response = await self._generate_with_image(prompt, image_b64, image_format)
        return self._parse_image_analysis_response(response)

    async def extract_radiology_measurements(
        self,
        findings_text: str,
        report_type: str
    ) -> List[StructuredMeasurement]:
        """
        Extract structured measurements from radiology findings text.
        
        Parses the textual findings from image analysis to identify
        measurable findings (nodules, masses, effusions, lesions, etc.)
        with their sizes and locations.
        
        Args:
            findings_text: Textual findings from analyze_radiology_image()
            report_type: Type of imaging study
        
        Returns:
            List of StructuredMeasurement objects
        """
        prompt = f"""From the following radiology findings, extract all measurable findings.
For each finding, provide the type, body region, size in millimeters, and a brief description.

Findings:
{findings_text}

Respond in this exact format for each measurable finding. Only include findings that have a size measurement.
FINDING: [type, e.g. nodule, mass, effusion, lesion, calcification, lymph node, cyst]
REGION: [body region, e.g. lung, liver, brain, kidney, breast, thyroid, spine]
SIZE_MM: [size in millimeters as a number, convert cm to mm if needed]
DESCRIPTION: [brief description]
---

If no measurable findings are present, respond with: NO_MEASUREMENTS"""

        response = await self._generate(prompt)
        return self._parse_measurements_response(response)

    def _parse_measurements_response(self, response: str) -> List[StructuredMeasurement]:
        """Parse structured measurement extraction response."""
        if "NO_MEASUREMENTS" in response.upper():
            return []

        measurements = []
        blocks = response.split("---")

        for block in blocks:
            if not block.strip():
                continue

            data = {}
            for line in block.strip().split("\n"):
                line = line.strip()
                if line.startswith("FINDING:"):
                    data["finding_type"] = line.replace("FINDING:", "").strip().lower()
                elif line.startswith("REGION:"):
                    data["region"] = line.replace("REGION:", "").strip().lower()
                elif line.startswith("SIZE_MM:"):
                    size_str = line.replace("SIZE_MM:", "").strip()
                    try:
                        data["size_mm"] = float(size_str.replace("mm", "").strip())
                    except (ValueError, TypeError):
                        pass
                elif line.startswith("DESCRIPTION:"):
                    data["description"] = line.replace("DESCRIPTION:", "").strip()

            if data.get("finding_type") and data.get("region") and data.get("size_mm"):
                measurements.append(StructuredMeasurement(
                    finding_type=data["finding_type"],
                    body_region=data["region"],
                    size_mm=data["size_mm"],
                    description=data.get("description", "")
                ))

        return measurements
    
    async def _generate_with_image(
        self,
        prompt: str,
        image_b64: str,
        image_format: str
    ) -> str:
        """Send multimodal generation request with image."""
        try:
            response = await self.client.post(
                f"{self.base_url}/generate",
                json={
                    "prompt": prompt,
                    "image": image_b64,
                    "image_format": image_format,
                    "max_tokens": 1024,
                    "temperature": 0.2,  # Low temp for medical accuracy
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", data.get("text", ""))
        except httpx.HTTPError as e:
            logger.error(f"MedGemma 4B image analysis failed: {e}")
            raise
    
    def _build_image_analysis_prompt(
        self,
        report_type: str,
        clinical_context: Optional[str]
    ) -> str:
        """Build prompt for radiology image analysis."""
        modality_map = {
            "xray": "chest X-ray",
            "ct": "CT scan",
            "mri": "MRI scan",
            "mra": "MR Angiography",
            "pet": "PET scan"
        }
        modality = modality_map.get(report_type, report_type.upper())
        
        prompt = f"""Analyze this {modality} image and describe your findings.

Provide a detailed description of:
1. Overall image quality and positioning
2. Normal anatomical structures visible
3. Any abnormalities or areas of concern
4. Specific observations that may require clinical attention

"""
        if clinical_context:
            prompt += f"Clinical Context: {clinical_context}\n\n"
        
        prompt += """Respond in this format:
FINDINGS: [Detailed description of what you observe in the image]
OBSERVATIONS:
- [Specific observation 1]
- [Specific observation 2]
ABNORMALITIES: [yes/no]
CONFIDENCE: [high/medium/low]"""
        
        return prompt
    
    def _parse_image_analysis_response(self, response: str) -> ImageAnalysisResult:
        """Parse image analysis response."""
        findings = ""
        observations = []
        abnormalities = False
        confidence = "medium"
        
        lines = response.strip().split("\n")
        current_section = None
        
        for line in lines:
            line = line.strip()
            if line.startswith("FINDINGS:"):
                findings = line.replace("FINDINGS:", "").strip()
                current_section = None
            elif line.startswith("OBSERVATIONS:"):
                current_section = "observations"
            elif line.startswith("ABNORMALITIES:"):
                abnorm_str = line.replace("ABNORMALITIES:", "").strip().lower()
                abnormalities = abnorm_str in ["yes", "true", "detected"]
                current_section = None
            elif line.startswith("CONFIDENCE:"):
                conf_str = line.replace("CONFIDENCE:", "").strip().lower()
                if conf_str in ["high", "medium", "low"]:
                    confidence = conf_str
                current_section = None
            elif line.startswith("- ") and current_section == "observations":
                observations.append(line[2:].strip())
        
        # If no structured findings, use the whole response
        if not findings:
            findings = response
        
        return ImageAnalysisResult(
            findings=findings,
            observations=observations,
            abnormalities_detected=abnormalities,
            confidence=confidence,
            raw_response=response
        )
    
    async def extract_lab_values(self, report_text: str) -> ExtractionResult:
        """
        Extract structured lab values from report text.
        
        Args:
            report_text: Raw text from lab report PDF
        """
        prompt = self._build_extraction_prompt(report_text)
        response = await self._generate(prompt)
        return self._parse_extraction_response(response)
    
    async def classify_report_type(self, report_text: str) -> str:
        """
        Classify the type of medical report.
        
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

    async def extract_patient_vitals(self, note_text: str) -> dict:
        """
        Extract vital signs from patient note text.
        
        Returns dict with: temperature, blood_pressure, heart_rate, sp02, weight, etc.
        """
        prompt = f"""Extract vital signs from this patient note. Return JSON format.

Patient Note:
{note_text}

Extract these vitals if present:
- temperature (in Fahrenheit)
- systolic (blood pressure systolic)
- diastolic (blood pressure diastolic)
- heart_rate (beats per minute)
- sp02 (oxygen saturation percentage)
- weight (in pounds)
- pain_scale (0-10)
- blood_sugar_level
- hemoglobin_a1c

Respond with JSON only, use null for missing values:
{{"temperature": null, "systolic": null, "diastolic": null, "heart_rate": null, "sp02": null, "weight": null, "pain_scale": null, "blood_sugar_level": null, "hemoglobin_a1c": null}}"""
        
        response = await self._generate(prompt)
        
        try:
            import json
            # Find JSON in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception as e:
            logger.warning(f"Failed to parse vitals JSON: {e}")
        
        return {}
    
    async def _generate(self, prompt: str) -> str:
        """Send generation request to MedGemma 4B."""
        try:
            response = await self.client.post(
                f"{self.base_url}/generate",
                json={
                    "prompt": prompt,
                    "max_tokens": 1024,
                    "temperature": 0.1,  # Low temp for extraction
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", data.get("text", ""))
        except httpx.HTTPError as e:
            logger.error(f"MedGemma 4B generation failed: {e}")
            raise
    
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

    def _parse_extraction_response(self, response: str) -> ExtractionResult:
        """Parse structured extraction response."""
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
    
    async def health_check(self) -> bool:
        """Check if MedGemma 4B server is reachable."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False
