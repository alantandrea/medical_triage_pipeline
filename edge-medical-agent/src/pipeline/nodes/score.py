"""
Step 7: Score - Calculate final priority score and level.

Uses enhanced trend severity for more nuanced scoring:
- CRITICAL trends get highest bonus
- SIGNIFICANT trends get moderate bonus
- Statistical significance adds additional weight
"""
import logging
import time
from typing import Any

from ..state import PipelineState
from ...config import settings
from ...models import TrendSeverity

logger = logging.getLogger(__name__)


async def score_node(state: PipelineState, pipeline_logger: Any = None) -> PipelineState:
    """
    Calculate final priority score incorporating all factors.
    
    Scoring factors:
    - Base AI urgency score (0-100)
    - Critical trend bonus (+20 per critical trend, max +40)
    - Significant change bonus (+10 per significant change, max +30)
    - Statistical significance bonus (+5 per statistically significant trend)
    - Critical flag bonus (+15 per critical value)
    - Report type modifier (path +10, radiology +5)
    
    Inputs:
        - urgency_score from AI analysis
        - trends with severity from historical
        - critical_trends from historical
        - rapid_changes from historical
        - extracted_lab_values with flags
        - classified_type
    
    Outputs:
        - final_score (0-100, capped)
        - priority_level: routine, followup, important, urgent
        - score_breakdown: detailed breakdown of score components
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    report_id = state["report_id"]
    
    logger.info(f"[{tenant_id}] Score: Calculating final score for {report_id}")
    
    try:
        # Start with AI urgency score
        base_score = state.get("urgency_score", 0)
        
        # Critical trend bonus (highest priority)
        critical_trends = state.get("critical_trends", [])
        critical_trend_bonus = min(len(critical_trends) * 20, 40)
        
        # Significant change bonus (from rapid_changes)
        rapid_changes = state.get("rapid_changes", [])
        significant_bonus = min(len(rapid_changes) * 10, 30)
        
        # Statistical significance bonus
        stat_sig_count = 0
        for trend in state.get("trends", []):
            if trend.get("statistically_significant", False):
                stat_sig_count += 1
        stat_sig_bonus = min(stat_sig_count * 5, 15)
        
        # Critical value bonus (from lab flags)
        critical_count = 0
        for lv in state.get("extracted_lab_values", []):
            flag = (lv.get("flag") or "").upper()
            if "CRITICAL" in flag:
                critical_count += 1
        critical_value_bonus = min(critical_count * 15, 45)
        
        # Report type modifier
        type_modifier = 0
        classified_type = state.get("classified_type", "")
        if classified_type == "path":
            type_modifier = 10  # Pathology always important
        elif classified_type in ["ct", "mri", "pet"]:
            type_modifier = 5  # Advanced imaging
        
        # Radiology growth bonus (from radiology_trends in historical)
        radiology_growth_bonus = 0
        radiology_trends = state.get("radiology_trends", [])
        for rt in radiology_trends:
            classification = rt.get("trend_classification", "stable")
            doubling_time = rt.get("doubling_time_days")
            growth_rate = rt.get("growth_rate_mm_per_month", 0)
            
            if classification == "growing":
                # Rapid doubling time (< 400 days) is very concerning for malignancy
                if doubling_time and doubling_time < 400:
                    radiology_growth_bonus += 25
                elif growth_rate > 2.0:
                    radiology_growth_bonus += 15
                else:
                    radiology_growth_bonus += 8
        radiology_growth_bonus = min(radiology_growth_bonus, 40)
        
        # Calculate final score (capped at 100)
        final_score = min(
            100,
            base_score + critical_trend_bonus + significant_bonus + 
            stat_sig_bonus + critical_value_bonus + type_modifier +
            radiology_growth_bonus
        )
        
        # Determine priority level
        if final_score >= settings.threshold_urgent:
            priority_level = "urgent"
        elif final_score >= settings.threshold_important:
            priority_level = "important"
        elif final_score >= settings.threshold_followup:
            priority_level = "followup"
        else:
            priority_level = "routine"
        
        state["final_score"] = final_score
        state["priority_level"] = priority_level
        
        # Store detailed breakdown for transparency
        state["score_breakdown"] = {
            "base_ai_score": base_score,
            "critical_trend_bonus": critical_trend_bonus,
            "significant_change_bonus": significant_bonus,
            "statistical_significance_bonus": stat_sig_bonus,
            "critical_value_bonus": critical_value_bonus,
            "report_type_modifier": type_modifier,
            "radiology_growth_bonus": radiology_growth_bonus,
            "final_score": final_score,
            "critical_trends_count": len(critical_trends),
            "significant_changes_count": len(rapid_changes),
            "stat_significant_count": stat_sig_count,
            "critical_values_count": critical_count,
            "radiology_trends_count": len(radiology_trends),
        }
        
        logger.info(
            f"[{tenant_id}] Score: base={base_score}, critical_trend={critical_trend_bonus}, "
            f"significant={significant_bonus}, stat_sig={stat_sig_bonus}, "
            f"critical_val={critical_value_bonus}, type_mod={type_modifier}, "
            f"rad_growth={radiology_growth_bonus} -> final={final_score} ({priority_level})"
        )
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["score"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="score", duration_ms=duration_ms,
                synopsis=f"Score {final_score} ({priority_level}): base={base_score} + trends={critical_trend_bonus} + sig={significant_bonus} + crit_val={critical_value_bonus} + type={type_modifier} + rad_growth={radiology_growth_bonus}",
                details=state["score_breakdown"],
            )
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Score failed: {e}")
        state.setdefault("errors", []).append(f"Score: {str(e)}")
        state["final_score"] = state.get("urgency_score", 50)
        state["priority_level"] = "followup"  # Default to followup on error
        state["score_breakdown"] = {"error": str(e)}
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="score", error=str(e),
                synopsis=f"Scoring failed, defaulting to {state['final_score']} ({state['priority_level']}): {e}",
            )
    
    return state
