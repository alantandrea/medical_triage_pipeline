"""
Tests for LangGraph pipeline.
"""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from src.pipeline.state import PipelineState
from src.pipeline.nodes.score import score_node
from src.pipeline.nodes.patient_context import _calculate_age


class TestPipelineState:
    """Tests for pipeline state."""
    
    def test_state_initialization(self):
        """Test state can be initialized with required fields."""
        state: PipelineState = {
            "tenant_id": "test-tenant",
            "report_id": "RPT-001",
            "patient_id": 12345,
            "report_type": "lab",
            "errors": [],
            "step_timings": {}
        }
        
        assert state["tenant_id"] == "test-tenant"
        assert state["report_id"] == "RPT-001"


class TestScoreNode:
    """Tests for scoring node."""
    
    @pytest.mark.asyncio
    async def test_score_routine(self):
        """Test routine priority scoring."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 20,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert result["final_score"] == 20
        assert result["priority_level"] == "routine"
    
    @pytest.mark.asyncio
    async def test_score_urgent_with_critical_values(self):
        """Test urgent priority with critical values."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 60,
            "rapid_changes": ["Glucose", "Potassium"],
            "extracted_lab_values": [
                {"flag": "CRITICAL_HIGH"},
                {"flag": "CRITICAL_LOW"}
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 60 base + 20 rapid (2*10) + 30 critical (2*15) = 110 -> capped at 100
        assert result["final_score"] == 100
        assert result["priority_level"] == "urgent"
    
    @pytest.mark.asyncio
    async def test_score_pathology_modifier(self):
        """Test pathology report type modifier."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 40,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "path",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # 40 base + 10 path modifier = 50
        assert result["final_score"] == 50
        assert result["priority_level"] == "important"
    
    @pytest.mark.asyncio
    async def test_score_followup_threshold(self):
        """Test followup threshold boundary."""
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": 30,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert result["final_score"] == 30
        assert result["priority_level"] == "followup"


class TestPatientContextHelpers:
    """Tests for patient context helper functions."""
    
    def test_calculate_age_valid(self):
        """Test age calculation with valid DOB."""
        # Person born in 1980 should be ~46 in 2026
        age = _calculate_age("1980-05-15")
        assert 45 <= age <= 46
    
    def test_calculate_age_invalid(self):
        """Test age calculation with invalid DOB returns 0."""
        age = _calculate_age("invalid-date")
        assert age == 0
    
    def test_calculate_age_future_birthday(self):
        """Test age calculation when birthday hasn't occurred yet this year."""
        # Use a date far in the future to ensure birthday hasn't passed
        age = _calculate_age("1980-12-31")
        assert age >= 45


class TestPipelineIntegration:
    """Integration tests for pipeline."""
    
    @pytest.mark.asyncio
    async def test_pipeline_creation(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client,
        mock_medgemma_27b,
        mock_medgemma_4b,
        mock_loinc_client
    ):
        """Test pipeline can be created with mocked dependencies."""
        from src.pipeline import create_triage_pipeline
        
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
