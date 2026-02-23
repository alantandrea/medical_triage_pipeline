"""
Step 5: Historical Analysis - Fetch prior lab values and calculate trends.

Uses enhanced vector analysis with:
- Per-test thresholds (different sensitivity for different tests)
- Rate of change (velocity) calculation
- Statistical significance analysis
- Trend severity classification
"""
import logging
import time
from typing import Any, List

from ..state import PipelineState
from ...config import settings
from ...models import TrendSeverity

logger = logging.getLogger(__name__)


async def historical_node(
    state: PipelineState,
    mongodb_client: Any,
    pipeline_logger: Any = None
) -> PipelineState:
    """
    Fetch historical lab values and identify trends/rapid changes.
    
    Uses enhanced vector analysis for:
    - Per-test thresholds (creatinine vs glucose have different significance)
    - Velocity (rate of change per day)
    - Statistical significance (z-score, coefficient of variation)
    - Trend severity classification (critical, significant, moderate, minimal, stable)
    
    Inputs:
        - patient_id, tenant_id
        - extracted_lab_values with loinc_codes
    
    Outputs:
        - historical_context (formatted for model)
        - trends: List of enhanced trend data
        - rapid_changes: List of tests with rapid changes
        - critical_trends: List of tests with critical severity
    """
    start = time.time()
    tenant_id = state["tenant_id"]
    patient_id = state["patient_id"]
    
    logger.info(f"[{tenant_id}] Historical: Analyzing trends for patient {patient_id}")
    
    try:
        lab_values = state.get("extracted_lab_values", [])
        
        trends = []
        rapid_changes = []
        critical_trends = []
        context_lines = []
        
        # Get enhanced trends for each extracted lab value with LOINC code
        for lv in lab_values:
            loinc_code = lv.get("loinc_code")
            if not loinc_code:
                continue
            
            # Use enhanced vector analysis
            analysis = await mongodb_client.get_enhanced_lab_trend(
                tenant_id,
                patient_id,
                loinc_code,
                days=settings.rapid_change_window_days,
                max_values=settings.max_historical_values
            )
            
            trend_dict = {
                "test_name": lv["test_name"],
                "loinc_code": loinc_code,
                "direction": "increasing" if analysis.delta_percent > 0 else "decreasing" if analysis.delta_percent < 0 else "stable",
                "delta_percent": round(analysis.total_delta_percent, 1),
                "rapid_change": analysis.rapid_change_flag,
                "prior_values": len(analysis.value_history),
                # Enhanced metrics
                "severity": analysis.trend_severity.value,
                "velocity_per_day": round(analysis.velocity_percent_per_day, 2),
                "acceleration": analysis.acceleration_direction,
                "z_score": round(analysis.z_score, 2),
                "statistically_significant": analysis.is_statistically_significant,
                "threshold_used": analysis.threshold_used,
                "clinical_notes": analysis.clinical_notes
            }
            trends.append(trend_dict)
            
            # Track by severity
            if analysis.trend_severity == TrendSeverity.CRITICAL:
                critical_trends.append(lv["test_name"])
                context_lines.append(
                    f"🚨 CRITICAL: {lv['test_name']}: {analysis.total_delta_percent:+.1f}% "
                    f"(velocity: {analysis.velocity_percent_per_day:+.2f}%/day, z-score: {analysis.z_score:.1f})"
                )
            elif analysis.trend_severity == TrendSeverity.SIGNIFICANT:
                rapid_changes.append(lv["test_name"])
                context_lines.append(
                    f"⚠️ {lv['test_name']}: {analysis.total_delta_percent:+.1f}% "
                    f"(threshold: {analysis.threshold_used}%, {analysis.acceleration_direction})"
                )
            elif analysis.trend_severity == TrendSeverity.MODERATE:
                context_lines.append(
                    f"📊 {lv['test_name']}: {analysis.total_delta_percent:+.1f}% (moderate change)"
                )
            elif len(analysis.value_history) > 1:
                context_lines.append(
                    f"{lv['test_name']}: {analysis.total_delta_percent:+.1f}% (stable)"
                )
        
        state["trends"] = trends
        state["rapid_changes"] = rapid_changes
        state["critical_trends"] = critical_trends
        state["historical_context"] = "\n".join(context_lines) if context_lines else "No prior lab data available"
        
        # Radiology trend analysis - check for prior imaging findings
        radiology_trends = []
        classified_type = state.get("classified_type", "")
        if classified_type in ["xray", "ct", "mri", "mra", "pet"]:
            try:
                # Look up prior radiology findings for this patient
                prior_findings = await mongodb_client.get_patient_radiology_findings(
                    tenant_id, patient_id
                )
                
                # Group by finding_type + body_region and get trends
                seen_combos = set()
                for pf in prior_findings:
                    combo = (pf.get("finding_type", ""), pf.get("body_region", ""))
                    if combo in seen_combos or not combo[0]:
                        continue
                    seen_combos.add(combo)
                    
                    trend = await mongodb_client.get_radiology_trend(
                        tenant_id=tenant_id,
                        patient_id=patient_id,
                        finding_type=combo[0],
                        body_region=combo[1]
                    )
                    
                    if len(trend.measurements) >= 2:
                        trend_dict = {
                            "finding_type": combo[0],
                            "body_region": combo[1],
                            "size_change_percent": round(trend.size_change_percent, 1),
                            "growth_rate_mm_per_month": round(trend.growth_rate_mm_per_month, 2),
                            "doubling_time_days": round(trend.doubling_time_days) if trend.doubling_time_days else None,
                            "trend_classification": trend.trend_classification,
                            "requires_followup": trend.requires_followup,
                            "measurement_count": len(trend.measurements),
                            "clinical_notes": trend.clinical_notes,
                        }
                        radiology_trends.append(trend_dict)
                        
                        # Add to context for the AI model
                        if trend.trend_classification == "growing":
                            severity_marker = "🚨 GROWING" if (trend.doubling_time_days and trend.doubling_time_days < 400) else "⚠️ Growing"
                            context_lines.append(
                                f"{severity_marker}: {combo[0]} in {combo[1]}: "
                                f"{trend.size_change_percent:+.1f}% ({trend.growth_rate_mm_per_month:+.2f} mm/month"
                                f"{f', doubling time {trend.doubling_time_days:.0f} days' if trend.doubling_time_days else ''})"
                            )
                            if trend.doubling_time_days and trend.doubling_time_days < 400:
                                critical_trends.append(f"{combo[0]}_{combo[1]}")
                            else:
                                rapid_changes.append(f"{combo[0]}_{combo[1]}")
                        elif trend.trend_classification == "shrinking":
                            context_lines.append(
                                f"📉 Shrinking: {combo[0]} in {combo[1]}: "
                                f"{trend.size_change_percent:+.1f}%"
                            )
                        elif trend.trend_classification == "stable":
                            context_lines.append(
                                f"{combo[0]} in {combo[1]}: stable"
                            )
                
                if radiology_trends:
                    logger.info(f"[{tenant_id}] Radiology trends: {len(radiology_trends)} findings tracked")
                    
            except Exception as e:
                logger.warning(f"[{tenant_id}] Radiology trend lookup failed: {e}")
        
        state["radiology_trends"] = radiology_trends
        # Re-update these since radiology trends may have added entries
        state["critical_trends"] = critical_trends
        state["rapid_changes"] = rapid_changes
        state["historical_context"] = "\n".join(context_lines) if context_lines else "No prior data available"
        
        if critical_trends:
            logger.warning(f"[{tenant_id}] CRITICAL trends detected: {critical_trends}")
        if rapid_changes:
            logger.warning(f"[{tenant_id}] Significant changes detected: {rapid_changes}")
        
        # Record timing
        duration_ms = int((time.time() - start) * 1000)
        state.setdefault("step_timings", {})["historical"] = duration_ms
        
        # Log to OpenSearch
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="historical", duration_ms=duration_ms,
                synopsis=f"{len(trends)} trends analyzed, {len(critical_trends)} critical, {len(rapid_changes)} significant, {len(radiology_trends)} radiology tracked",
                details={
                    "trend_count": len(trends),
                    "critical_trends": critical_trends[:5],
                    "significant_changes": rapid_changes[:5],
                    "radiology_trends_count": len(radiology_trends),
                    "radiology_trends": [
                        {"finding": rt["finding_type"], "region": rt["body_region"],
                         "classification": rt["trend_classification"],
                         "growth_rate": rt.get("growth_rate_mm_per_month")}
                        for rt in radiology_trends[:5]
                    ],
                    "historical_context_preview": (state.get("historical_context") or "")[:300],
                },
            )
        
        logger.info(
            f"[{tenant_id}] Historical complete: {len(trends)} trends, "
            f"{len(critical_trends)} critical, {len(rapid_changes)} significant"
        )
        
    except Exception as e:
        logger.error(f"[{tenant_id}] Historical failed: {e}")
        state.setdefault("errors", []).append(f"Historical: {str(e)}")
        state["trends"] = []
        state["rapid_changes"] = []
        state["critical_trends"] = []
        state["historical_context"] = "Historical analysis unavailable"
        if pipeline_logger:
            await pipeline_logger.log_step(
                state=state, step="historical", error=str(e),
                synopsis=f"Historical analysis failed: {e}",
            )
    
    return state
