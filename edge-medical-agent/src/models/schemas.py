"""
Pydantic models for MedGemma Triage System.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
from datetime import datetime
from enum import Enum


class TrendDirection(str, Enum):
    """Direction of lab value trend."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    UNKNOWN = "unknown"


class Patient(BaseModel):
    """Patient demographics from AWS API."""
    patient_id: int
    first_name: str
    last_name: str
    patient_dob: str
    sex: str
    cell_phone: Optional[str] = None
    home_phone: Optional[str] = None
    work_phone: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PendingReport(BaseModel):
    """Report from GET /reports/pending."""
    patient_id: int
    report_id: str
    report_date: str
    report_type: str  # lab, xray, ct, mri, mra, pet, path
    reporting_source: str
    severity: str  # normal, minor, major, critical
    report_final_ind: str  # "true" or "false" (string, not bool!)
    created_at: str
    report_pdf_url: str
    report_image_url: Optional[str] = None


class PendingNote(BaseModel):
    """Patient note from GET /notes/pending."""
    patient_id: int
    note_id: str
    patient_name: str
    note_date: str
    note_text: str
    # Pre-extracted vitals (from Bedrock Haiku)
    temperature: Optional[float] = None
    pain_scale: Optional[int] = None
    sp02: Optional[float] = None
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    weight: Optional[float] = None
    blood_sugar_level: Optional[float] = None
    heart_rate: Optional[int] = None
    hemoglobin_a1c: Optional[float] = None
    # Extracted symptoms
    symptoms: List[str] = Field(default_factory=list)
    urgency_indicators: List[str] = Field(default_factory=list)
    has_urgency: bool = False
    report_type: str = "patient_note"


class PatientReport(BaseModel):
    """In-flight report state stored in Redis."""
    report_id: str
    patient_id: int
    report_date: datetime
    report_type: str
    lab_report_doc: Optional[bytes] = None
    radiology_image: Optional[bytes] = None
    image_file_format: Optional[int] = None  # 1: jpeg, 2: png
    model_notes: str = ""
    image_followup: bool = False
    score: int = 0
    
    class Config:
        arbitrary_types_allowed = True


class ReportFinding(BaseModel):
    """Individual finding discovered during analysis."""
    report_id: str
    finding_id: str
    finding_notation: str
    urgency_score: int = Field(ge=0, le=100)
    next_steps: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StructuredLabValue(BaseModel):
    """Structured lab value for MongoDB storage."""
    tenant_id: str
    patient_id: int
    report_id: str
    collection_date: datetime
    test_name: str
    loinc_code: Optional[str] = None
    value: float
    unit: str
    reference_range_low: Optional[float] = None
    reference_range_high: Optional[float] = None
    flag: Optional[str] = None  # HIGH, LOW, CRITICAL_HIGH, CRITICAL_LOW, NORMAL
    raw_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LabValueTrend(BaseModel):
    """Trend information for a single lab test."""
    test_name: str
    loinc_code: Optional[str] = None
    values: List[Tuple[datetime, float]] = Field(default_factory=list)
    trend_direction: TrendDirection = TrendDirection.UNKNOWN
    delta_percentage: float = 0.0
    rapid_change_flag: bool = False


class HistoricalContext(BaseModel):
    """Historical context for vector analysis."""
    patient_id: int
    relevant_tests: List[LabValueTrend] = Field(default_factory=list)
    context_string: str = ""
    has_prior_data: bool = False
