"""
Pipeline state definition for LangGraph.
"""
from typing import TypedDict, Optional, List, Any
from datetime import datetime


class PipelineState(TypedDict, total=False):
    """
    State passed through the LangGraph pipeline.
    Each node reads and updates this state.
    """
    # Input identifiers
    tenant_id: str
    report_id: str
    patient_id: int
    report_type: str  # lab, xray, ct, mri, mra, pet, path
    pdf_url: Optional[str]  # Pre-signed S3 URL for PDF download
    image_url: Optional[str]  # Pre-signed S3 URL for image download
    
    # Raw content
    pdf_bytes: Optional[bytes]
    image_bytes: Optional[bytes]
    image_format: Optional[str]  # jpeg, png
    
    # Step 1: Intake
    report_date: Optional[datetime]
    reporting_source: Optional[str]
    is_final: bool
    
    # Step 2: Classification
    classified_type: Optional[str]
    
    # Step 3: Extraction (27B model)
    extracted_text: Optional[str]
    extracted_lab_values: List[dict]
    loinc_mappings: dict  # test_name -> loinc_code
    
    # Step 4: Patient context
    patient_name: Optional[str]
    patient_dob: Optional[str]
    patient_context: Optional[str]
    
    # Step 5: Historical analysis
    historical_context: Optional[str]
    trends: List[dict]
    rapid_changes: List[str]
    critical_trends: List[str]
    radiology_trends: List[dict]
    
    # Step 6: AI Analysis (27B model)
    analysis_summary: Optional[str]
    findings: List[dict]
    urgency_score: int
    recommendations: List[str]
    
    # Step 6 (Radiology): Intermediate 4B image analysis results
    image_findings: Optional[str]  # Textual findings from 4B
    image_observations: List[str]  # Specific observations from 4B
    image_abnormalities: bool  # Whether abnormalities detected
    radiology_measurements: List[dict]  # Structured measurements stored in MongoDB
    
    # Step 7: Scoring
    final_score: int
    priority_level: str  # routine, followup, important, urgent
    
    # Step 8: Notification
    notification_sent: bool
    notification_type: Optional[str]
    notification_recipients: List[str]
    
    # Analysis metadata
    analysis_failed: bool  # True if AI analysis failed and urgency was escalated
    
    # Metadata
    processing_started: Optional[datetime]
    processing_completed: Optional[datetime]
    errors: List[str]
    step_timings: dict  # step_name -> duration_ms
