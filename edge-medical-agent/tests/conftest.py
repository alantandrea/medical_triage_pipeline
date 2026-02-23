"""
Pytest fixtures for MedGemma Triage System tests.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from src.models import Patient, PendingReport, StructuredLabValue
from src.models.loinc import LOINCCode, LOINCLookupResult

# Configure hypothesis for property-based tests
try:
    from hypothesis import settings as hyp_settings, Verbosity
    hyp_settings.register_profile("ci", max_examples=50, deadline=None)
    hyp_settings.register_profile("dev", max_examples=10, deadline=None)
    hyp_settings.register_profile("debug", max_examples=5, verbosity=Verbosity.verbose, deadline=None)
    hyp_settings.load_profile("dev")
except ImportError:
    pass  # hypothesis not installed


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_patient():
    """Sample patient for testing."""
    return Patient(
        patient_id=12345,
        first_name="John",
        last_name="Doe",
        patient_dob="1980-05-15",
        sex="M",
        cell_phone="555-1234",
        city="Boston",
        state="MA",
        zipcode="02101"
    )


@pytest.fixture
def sample_pending_report():
    """Sample pending report for testing."""
    return PendingReport(
        patient_id=12345,
        report_id="RPT-001",
        report_date="2026-02-09",
        report_type="lab",
        reporting_source="Quest Diagnostics",
        severity="normal",
        report_final_ind="true",
        created_at="2026-02-09T10:00:00Z",
        report_pdf_url="https://example.com/report.pdf"
    )


@pytest.fixture
def sample_lab_values():
    """Sample structured lab values."""
    return [
        StructuredLabValue(
            tenant_id="test-tenant",
            patient_id=12345,
            report_id="RPT-001",
            collection_date=datetime(2026, 2, 9),
            test_name="Glucose",
            loinc_code="2345-7",
            value=126.0,
            unit="mg/dL",
            reference_range_low=70.0,
            reference_range_high=100.0,
            flag="HIGH",
            raw_text="Glucose: 126 mg/dL (70-100)"
        ),
        StructuredLabValue(
            tenant_id="test-tenant",
            patient_id=12345,
            report_id="RPT-001",
            collection_date=datetime(2026, 2, 9),
            test_name="Hemoglobin A1c",
            loinc_code="4548-4",
            value=7.2,
            unit="%",
            reference_range_low=4.0,
            reference_range_high=5.6,
            flag="HIGH",
            raw_text="HbA1c: 7.2% (4.0-5.6)"
        )
    ]


@pytest.fixture
def sample_loinc_code():
    """Sample LOINC code."""
    return LOINCCode(
        loinc_num="2345-7",
        long_common_name="Glucose [Mass/volume] in Serum or Plasma",
        short_name="Glucose SerPl-mCnc",
        component="Glucose",
        property="MCnc",
        time_aspect="Pt",
        system="Ser/Plas",
        scale_type="Qn",
        loinc_class="CHEM",
        class_type="1",
        status="ACTIVE"
    )


@pytest.fixture
def mock_aws_client():
    """Mock AWS API client."""
    client = AsyncMock()
    client.get_pending_reports.return_value = []
    client.get_patient.return_value = None
    client.download_pdf.return_value = b"%PDF-1.4 test content"
    client.download_image.return_value = b"\xff\xd8\xff test jpeg"
    client.health_check.return_value = True
    return client


@pytest.fixture
def mock_mongodb_client(sample_patient, sample_lab_values):
    """Mock MongoDB client."""
    client = AsyncMock()
    client.get_patient.return_value = sample_patient
    client.get_patient_lab_history.return_value = sample_lab_values
    client.health_check.return_value = True
    return client


@pytest.fixture
def mock_redis_client():
    """Mock Redis client."""
    client = AsyncMock()
    client.health_check.return_value = True
    client.acquire_lock.return_value = True
    
    # Mock the underlying client property
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {}
    mock_redis.get.return_value = None
    client.client = mock_redis
    
    return client


@pytest.fixture
def mock_medgemma_27b():
    """Mock MedGemma 27B client."""
    from src.clients.medgemma_27b import AnalysisResult
    
    client = AsyncMock()
    client.analyze_lab_report.return_value = AnalysisResult(
        summary="Elevated glucose and HbA1c suggest diabetes management review needed",
        findings=["Glucose elevated at 126 mg/dL", "HbA1c elevated at 7.2%"],
        urgency_score=45,
        recommendations=["Review diabetes management", "Consider medication adjustment"],
        raw_response="test response"
    )
    client.health_check.return_value = True
    return client


@pytest.fixture
def mock_medgemma_4b():
    """Mock MedGemma 4B client."""
    from src.clients.medgemma_4b import ExtractionResult, ExtractedLabValue
    
    client = AsyncMock()
    client.extract_lab_values.return_value = ExtractionResult(
        lab_values=[
            ExtractedLabValue(test_name="Glucose", value="126", unit="mg/dL", flag="HIGH"),
            ExtractedLabValue(test_name="Hemoglobin A1c", value="7.2", unit="%", flag="HIGH")
        ],
        raw_response="test response"
    )
    client.classify_report_type.return_value = "lab"
    client.health_check.return_value = True
    return client


@pytest.fixture
def mock_loinc_client(sample_loinc_code):
    """Mock LOINC client."""
    client = AsyncMock()
    client.lookup_by_name.return_value = LOINCLookupResult(
        code=sample_loinc_code,
        found=True,
        match_type="normalized",
        query="Glucose",
        confidence=0.95
    )
    client.lookup_by_code.return_value = LOINCLookupResult(
        code=sample_loinc_code,
        found=True,
        match_type="exact",
        query="2345-7",
        confidence=1.0
    )
    return client


@pytest.fixture
def mock_notification_service():
    """Mock notification service."""
    service = AsyncMock()
    service.send_urgent_alert.return_value = True
    service.send_important_notification.return_value = True
    service.health_check.return_value = True
    return service
