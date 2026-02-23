"""
Property-based tests for scoring logic.

These tests verify that the scoring algorithm maintains its invariants
across a wide range of inputs.
"""
import pytest
from hypothesis import given, strategies as st, settings as hyp_settings
from hypothesis import assume

from src.pipeline.nodes.score import score_node
from src.pipeline.state import PipelineState


class TestScoringProperties:
    """Property-based tests for scoring node."""
    
    @given(
        base_score=st.integers(min_value=0, max_value=100),
        num_rapid_changes=st.integers(min_value=0, max_value=10),
        num_critical_values=st.integers(min_value=0, max_value=10),
        report_type=st.sampled_from(["lab", "xray", "ct", "mri", "pet", "path"])
    )
    @hyp_settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_score_always_bounded(
        self,
        base_score: int,
        num_rapid_changes: int,
        num_critical_values: int,
        report_type: str
    ):
        """
        Property: Final score is always between 0 and 100.
        
        **Validates: Requirements 8.1** - Score must be bounded
        """
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [f"test_{i}" for i in range(num_rapid_changes)],
            "extracted_lab_values": [
                {"flag": "CRITICAL_HIGH"} for _ in range(num_critical_values)
            ],
            "classified_type": report_type,
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        assert 0 <= result["final_score"] <= 100
    
    @given(
        base_score=st.integers(min_value=0, max_value=100),
        num_rapid_changes=st.integers(min_value=0, max_value=10),
        num_critical_values=st.integers(min_value=0, max_value=10)
    )
    @hyp_settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_score_monotonic_with_severity(
        self,
        base_score: int,
        num_rapid_changes: int,
        num_critical_values: int
    ):
        """
        Property: Adding more critical values or rapid changes never decreases score.
        
        **Validates: Requirements 8.2** - Severity increases score
        """
        # Base state
        base_state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        # State with more severity indicators
        severe_state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [f"test_{i}" for i in range(num_rapid_changes)],
            "extracted_lab_values": [
                {"flag": "CRITICAL_HIGH"} for _ in range(num_critical_values)
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        base_result = await score_node(base_state)
        severe_result = await score_node(severe_state)
        
        assert severe_result["final_score"] >= base_result["final_score"]
    
    @given(base_score=st.integers(min_value=0, max_value=100))
    @hyp_settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_priority_level_consistent_with_score(self, base_score: int):
        """
        Property: Priority level is always consistent with score thresholds.
        
        **Validates: Requirements 8.3** - Priority levels match thresholds
        """
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        score = result["final_score"]
        level = result["priority_level"]
        
        # Verify consistency with thresholds
        if score >= 75:
            assert level == "urgent"
        elif score >= 50:
            assert level == "important"
        elif score >= 30:
            assert level == "followup"
        else:
            assert level == "routine"
    
    @given(
        base_score=st.integers(min_value=0, max_value=100),
        num_rapid=st.integers(min_value=0, max_value=20)
    )
    @hyp_settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_rapid_change_bonus_capped(self, base_score: int, num_rapid: int):
        """
        Property: Rapid change bonus is capped at 30.
        
        **Validates: Requirements 8.4** - Bonus caps prevent runaway scores
        """
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [f"test_{i}" for i in range(num_rapid)],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # Max rapid bonus is 30, so score should be at most base + 30
        expected_max = min(100, base_score + 30)
        assert result["final_score"] <= expected_max
    
    @given(
        base_score=st.integers(min_value=0, max_value=100),
        num_critical=st.integers(min_value=0, max_value=20)
    )
    @hyp_settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_critical_value_bonus_capped(self, base_score: int, num_critical: int):
        """
        Property: Critical value bonus is capped at 45.
        
        **Validates: Requirements 8.5** - Critical bonus cap
        """
        state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [],
            "extracted_lab_values": [
                {"flag": "CRITICAL_HIGH"} for _ in range(num_critical)
            ],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        result = await score_node(state)
        
        # Max critical bonus is 45
        expected_max = min(100, base_score + 45)
        assert result["final_score"] <= expected_max
    
    @given(base_score=st.integers(min_value=0, max_value=100))
    @hyp_settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_pathology_always_adds_modifier(self, base_score: int):
        """
        Property: Pathology reports always get +10 modifier.
        
        **Validates: Requirements 8.6** - Report type modifiers
        """
        lab_state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "lab",
            "step_timings": {}
        }
        
        path_state: PipelineState = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "urgency_score": base_score,
            "rapid_changes": [],
            "extracted_lab_values": [],
            "classified_type": "path",
            "step_timings": {}
        }
        
        lab_result = await score_node(lab_state)
        path_result = await score_node(path_state)
        
        # Pathology should be 10 points higher (unless capped)
        expected_diff = min(10, 100 - lab_result["final_score"])
        assert path_result["final_score"] == lab_result["final_score"] + expected_diff
