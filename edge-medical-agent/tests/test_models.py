"""
Tests for Pydantic models.
"""
import pytest
from datetime import datetime

from src.models import (
    Patient,
    PendingReport,
    StructuredLabValue,
    LabValueTrend,
    TrendDirection,
)
from src.models.loinc import LOINCCode, LOINCLookupResult, LOINCSynonymEntry


class TestPatientModel:
    """Tests for Patient model."""
    
    def test_patient_creation(self, sample_patient):
        """Test basic patient creation."""
        assert sample_patient.patient_id == 12345
        assert sample_patient.first_name == "John"
        assert sample_patient.last_name == "Doe"
        assert sample_patient.sex == "M"
    
    def test_patient_optional_fields(self):
        """Test patient with minimal required fields."""
        patient = Patient(
            patient_id=1,
            first_name="Jane",
            last_name="Smith",
            patient_dob="1990-01-01",
            sex="F"
        )
        assert patient.cell_phone is None
        assert patient.city is None


class TestPendingReportModel:
    """Tests for PendingReport model."""
    
    def test_pending_report_creation(self, sample_pending_report):
        """Test pending report creation."""
        assert sample_pending_report.report_id == "RPT-001"
        assert sample_pending_report.report_type == "lab"
        assert sample_pending_report.severity == "normal"
    
    def test_report_final_indicator_is_string(self, sample_pending_report):
        """Verify report_final_ind is string not bool."""
        assert sample_pending_report.report_final_ind == "true"
        assert isinstance(sample_pending_report.report_final_ind, str)


class TestStructuredLabValue:
    """Tests for StructuredLabValue model."""
    
    def test_lab_value_creation(self, sample_lab_values):
        """Test lab value creation."""
        glucose = sample_lab_values[0]
        assert glucose.test_name == "Glucose"
        assert glucose.value == 126.0
        assert glucose.flag == "HIGH"
        assert glucose.loinc_code == "2345-7"
    
    def test_lab_value_reference_range(self, sample_lab_values):
        """Test reference range fields."""
        glucose = sample_lab_values[0]
        assert glucose.reference_range_low == 70.0
        assert glucose.reference_range_high == 100.0


class TestLabValueTrend:
    """Tests for LabValueTrend model."""
    
    def test_trend_creation(self):
        """Test trend creation."""
        trend = LabValueTrend(
            test_name="Glucose",
            loinc_code="2345-7",
            values=[(datetime.now(), 126.0), (datetime.now(), 110.0)],
            trend_direction=TrendDirection.INCREASING,
            delta_percentage=14.5,
            rapid_change_flag=False
        )
        assert trend.test_name == "Glucose"
        assert trend.trend_direction == TrendDirection.INCREASING
        assert len(trend.values) == 2
    
    def test_trend_direction_enum(self):
        """Test TrendDirection enum values."""
        assert TrendDirection.INCREASING.value == "increasing"
        assert TrendDirection.DECREASING.value == "decreasing"
        assert TrendDirection.STABLE.value == "stable"


class TestLOINCCode:
    """Tests for LOINCCode model."""
    
    def test_loinc_code_creation(self, sample_loinc_code):
        """Test LOINC code creation."""
        assert sample_loinc_code.loinc_num == "2345-7"
        assert sample_loinc_code.component == "Glucose"
        assert sample_loinc_code.status == "ACTIVE"
    
    def test_loinc_code_validation_valid(self):
        """Test valid LOINC code format."""
        code = LOINCCode(
            loinc_num="2345-7",
            long_common_name="Test"
        )
        assert code.loinc_num == "2345-7"
    
    def test_loinc_code_validation_invalid_format(self):
        """Test invalid LOINC code format raises error."""
        with pytest.raises(ValueError):
            LOINCCode(
                loinc_num="invalid",
                long_common_name="Test"
            )
    
    def test_loinc_to_redis_hash(self, sample_loinc_code):
        """Test conversion to Redis hash."""
        hash_data = sample_loinc_code.to_redis_hash()
        assert hash_data["loinc_num"] == "2345-7"
        assert hash_data["component"] == "Glucose"
        assert "long_common_name" in hash_data
    
    def test_loinc_from_redis_hash(self):
        """Test creation from Redis hash."""
        hash_data = {
            "loinc_num": "2345-7",
            "long_common_name": "Glucose Test",
            "component": "Glucose",
            "status": "ACTIVE"
        }
        code = LOINCCode.from_redis_hash(hash_data)
        assert code.loinc_num == "2345-7"
        assert code.long_common_name == "Glucose Test"


class TestLOINCLookupResult:
    """Tests for LOINCLookupResult model."""
    
    def test_lookup_result_found(self, sample_loinc_code):
        """Test successful lookup result."""
        result = LOINCLookupResult(
            code=sample_loinc_code,
            found=True,
            match_type="exact",
            query="2345-7",
            confidence=1.0
        )
        assert result.found is True
        assert result.match_type == "exact"
        assert result.confidence == 1.0
    
    def test_lookup_result_not_found(self):
        """Test unsuccessful lookup result."""
        result = LOINCLookupResult(
            found=False,
            match_type="none",
            query="unknown test"
        )
        assert result.found is False
        assert result.code is None


class TestLOINCSynonymEntry:
    """Tests for LOINCSynonymEntry model."""
    
    def test_synonym_entry_creation(self):
        """Test synonym entry creation."""
        entry = LOINCSynonymEntry(
            synonym="GLU",
            canonical="glucose",
            source="common_abbreviation"
        )
        assert entry.synonym == "GLU"
        assert entry.canonical == "glucose"
        assert entry.source == "common_abbreviation"
