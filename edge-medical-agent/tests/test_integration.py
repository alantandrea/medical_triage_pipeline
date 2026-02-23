"""
Integration tests for the full pipeline.

These tests verify that components work together correctly.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.pipeline import create_triage_pipeline, PipelineState
from src.pipeline.nodes.score import score_node
from src.pipeline.nodes.patient_context import patient_context_node, _calculate_age
from src.models import Patient, StructuredLabValue


class TestPipelineIntegration:
    """Integration tests for the full pipeline."""
    
    @pytest.mark.asyncio
    async def test_pipeline_creation_with_all_clients(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client,
        mock_medgemma_27b,
        mock_medgemma_4b,
        mock_loinc_client
    ):
        """Test pipeline can be created with all mocked clients."""
        pipeline = create_triage_pipeline(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            medgemma_27b=mock_medgemma_27b,
            medgemma_4b=mock_medgemma_4b,
            loinc_client=mock_loinc_client
        )
        
        assert pipeline is not None
        assert pipeline._graph is not None
    
    @pytest.mark.asyncio
    async def test_score_node_with_real_state(self):
        """Test score node with realistic state."""
        state: PipelineState = {
            "tenant_id": "test-tenant",
            "report_id": "RPT-001",
            "patient_id": 12345,
            "urgency_score": 55,
            "rapid_changes": ["Glucose"],
            "extracted_lab_values": [
                {"test_name": "Glucose", "value": 250, "flag": "CRITICAL_HIGH"},
                {"test_name": "HbA1c", "value": 9.5, "flag": "HIGH"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 55 base + 10 rapid (1 change) + 15 critical (1 critical) = 80
        assert result["final_score"] == 80
        assert result["priority_level"] == "urgent"
        assert "score" in result["step_timings"]
    
    @pytest.mark.asyncio
    async def test_patient_context_node_with_mock(self, mock_mongodb_client, sample_patient):
        """Test patient context node with mocked MongoDB."""
        state: PipelineState = {
            "tenant_id": "test-tenant",
            "report_id": "RPT-001",
            "patient_id": 12345,
            "step_timings": {}
        }
        
        result = await patient_context_node(state, mock_mongodb_client)
        
        assert result["patient_name"] == "John Doe"
        assert result["patient_dob"] == "1980-05-15"
        assert "Age:" in result["patient_context"]
        assert "Sex: M" in result["patient_context"]
    
    @pytest.mark.asyncio
    async def test_patient_context_node_patient_not_found(self, mock_mongodb_client):
        """Test patient context when patient not found."""
        mock_mongodb_client.get_patient.return_value = None
        
        state: PipelineState = {
            "tenant_id": "test-tenant",
            "report_id": "RPT-001",
            "patient_id": 99999,
            "step_timings": {}
        }
        
        result = await patient_context_node(state, mock_mongodb_client)
        
        assert result["patient_context"] == "Patient demographics unavailable"


class TestScoreCalculation:
    """Tests for score calculation logic."""
    
    @pytest.mark.asyncio
    async def test_score_routine_lab(self):
        """Test routine lab report scoring."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 15,
            "rapid_changes": [],
            "extracted_lab_values": [
                {"test_name": "Glucose", "value": 95, "flag": "NORMAL"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert result["final_score"] == 15
        assert result["priority_level"] == "routine"
    
    @pytest.mark.asyncio
    async def test_score_followup_with_abnormal(self):
        """Test followup scoring with abnormal values."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 35,
            "rapid_changes": [],
            "extracted_lab_values": [
                {"test_name": "Glucose", "value": 130, "flag": "HIGH"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert result["final_score"] == 35
        assert result["priority_level"] == "followup"
    
    @pytest.mark.asyncio
    async def test_score_important_pathology(self):
        """Test important scoring for pathology report."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 45,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "path",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 45 + 10 (path modifier) = 55
        assert result["final_score"] == 55
        assert result["priority_level"] == "important"
    
    @pytest.mark.asyncio
    async def test_score_urgent_multiple_factors(self):
        """Test urgent scoring with multiple severity factors."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 50,
            "rapid_changes": ["Potassium", "Sodium", "Glucose"],
            "extracted_lab_values": [
                {"flag": "CRITICAL_HIGH"},
                {"flag": "CRITICAL_LOW"},
                {"flag": "HIGH"}
            ],
            "classified_type": "ct",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 50 base + 30 rapid (3*10, capped) + 30 critical (2*15) + 5 (CT) = 115 -> capped at 100
        assert result["final_score"] == 100
        assert result["priority_level"] == "urgent"


class TestAgeCalculation:
    """Tests for age calculation helper."""
    
    def test_age_calculation_standard(self):
        """Test standard age calculation."""
        # Person born in 1980 should be ~46 in 2026
        age = _calculate_age("1980-05-15")
        assert 45 <= age <= 46
    
    def test_age_calculation_birthday_passed(self):
        """Test age when birthday has passed this year."""
        age = _calculate_age("1980-01-01")
        assert age == 46  # Birthday already passed in 2026
    
    def test_age_calculation_birthday_not_passed(self):
        """Test age when birthday hasn't passed yet."""
        age = _calculate_age("1980-12-31")
        assert age == 45  # Birthday hasn't passed yet in Feb 2026
    
    def test_age_calculation_invalid_date(self):
        """Test age calculation with invalid date."""
        age = _calculate_age("invalid")
        assert age == 0
    
    def test_age_calculation_empty_string(self):
        """Test age calculation with empty string."""
        age = _calculate_age("")
        assert age == 0


class TestEndToEndScenarios:
    """End-to-end scenario tests."""
    
    @pytest.mark.asyncio
    async def test_scenario_diabetic_patient_high_glucose(self):
        """
        Scenario: Diabetic patient with high glucose and HbA1c.
        Expected: Important priority due to elevated values.
        """
        state: PipelineState = {
            "tenant_id": "practice-001",
            "report_id": "RPT-DIAB-001",
            "patient_id": 12345,
            "urgency_score": 45,  # AI determined moderate concern
            "rapid_changes": ["Glucose"],  # Glucose trending up
            "extracted_lab_values": [
                {"test_name": "Glucose", "value": 180, "flag": "HIGH"},
                {"test_name": "HbA1c", "value": 8.5, "flag": "HIGH"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 45 + 10 (1 rapid change) = 55
        assert result["final_score"] == 55
        assert result["priority_level"] == "important"
    
    @pytest.mark.asyncio
    async def test_scenario_critical_potassium(self):
        """
        Scenario: Patient with critical potassium level.
        Expected: Urgent priority due to critical value.
        """
        state: PipelineState = {
            "tenant_id": "practice-001",
            "report_id": "RPT-CRIT-001",
            "patient_id": 67890,
            "urgency_score": 70,  # AI flagged as concerning
            "rapid_changes": [],
            "extracted_lab_values": [
                {"test_name": "Potassium", "value": 6.8, "flag": "CRITICAL_HIGH"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 70 + 15 (1 critical) = 85
        assert result["final_score"] == 85
        assert result["priority_level"] == "urgent"
    
    @pytest.mark.asyncio
    async def test_scenario_routine_annual_labs(self):
        """
        Scenario: Routine annual lab work, all normal.
        Expected: Routine priority.
        """
        state: PipelineState = {
            "tenant_id": "practice-001",
            "report_id": "RPT-ANNUAL-001",
            "patient_id": 11111,
            "urgency_score": 10,  # AI found nothing concerning
            "rapid_changes": [],
            "extracted_lab_values": [
                {"test_name": "Glucose", "value": 92, "flag": "NORMAL"},
                {"test_name": "Cholesterol", "value": 180, "flag": "NORMAL"},
                {"test_name": "TSH", "value": 2.1, "flag": "NORMAL"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert result["final_score"] == 10
        assert result["priority_level"] == "routine"
    
    @pytest.mark.asyncio
    async def test_scenario_pathology_biopsy(self):
        """
        Scenario: Pathology biopsy result.
        Expected: Important priority (pathology always gets +10).
        """
        state: PipelineState = {
            "tenant_id": "practice-001",
            "report_id": "RPT-PATH-001",
            "patient_id": 22222,
            "urgency_score": 40,  # AI analysis
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "path",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 40 + 10 (path modifier) = 50
        assert result["final_score"] == 50
        assert result["priority_level"] == "important"
