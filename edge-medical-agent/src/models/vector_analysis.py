"""
Enhanced vector analysis for lab values and radiology findings.

Provides:
1. Rate of change (velocity) - how fast is the value changing?
2. Acceleration - is the change speeding up or slowing down?
3. Statistical significance - is this change within normal variation?
4. Clinical context - per-test thresholds and interpretations
"""
from typing import List, Tuple, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from enum import Enum
import math

from .thresholds import get_threshold_for_test, get_rapid_change_threshold, get_threshold_source


class TrendSeverity(str, Enum):
    """Severity classification for trends."""
    CRITICAL = "critical"      # Immediate attention required
    SIGNIFICANT = "significant"  # Notable change, needs review
    MODERATE = "moderate"      # Worth monitoring
    MINIMAL = "minimal"        # Within normal variation
    STABLE = "stable"          # No significant change


class VectorAnalysis(BaseModel):
    """Comprehensive vector analysis for a lab test."""
    test_name: str
    loinc_code: Optional[str] = None
    
    # Basic trend data
    current_value: float
    previous_value: Optional[float] = None
    oldest_value: Optional[float] = None
    unit: str = ""
    
    # Time information
    current_date: datetime
    previous_date: Optional[datetime] = None
    oldest_date: Optional[datetime] = None
    days_span: int = 0
    
    # Delta calculations
    delta_absolute: float = 0.0  # Absolute change from previous
    delta_percent: float = 0.0   # Percentage change from previous
    total_delta_percent: float = 0.0  # Percentage change from oldest
    
    # Velocity (rate of change)
    velocity_per_day: float = 0.0  # Units per day
    velocity_percent_per_day: float = 0.0  # Percent per day
    
    # Acceleration (change in velocity)
    acceleration: float = 0.0  # Is velocity increasing or decreasing?
    acceleration_direction: str = "stable"  # accelerating, decelerating, stable
    
    # Statistical analysis
    mean_value: float = 0.0
    std_deviation: float = 0.0
    z_score: float = 0.0  # How many std devs from mean
    coefficient_of_variation: float = 0.0  # CV = std/mean * 100
    is_statistically_significant: bool = False
    
    # Clinical interpretation
    trend_severity: TrendSeverity = TrendSeverity.STABLE
    rapid_change_flag: bool = False
    threshold_used: float = 20.0  # The threshold that was applied
    clinical_notes: str = ""
    
    # Raw data
    value_history: List[Tuple[datetime, float]] = Field(default_factory=list)


class RadiologyTrend(BaseModel):
    """Trend tracking for radiology findings."""
    patient_id: int
    finding_type: str  # e.g., "nodule", "mass", "effusion"
    body_region: str   # e.g., "lung", "liver", "brain"
    
    # Measurements over time
    measurements: List[Tuple[datetime, float, str]] = Field(default_factory=list)  # (date, size_mm, notes)
    
    # Trend analysis
    size_change_percent: float = 0.0
    growth_rate_mm_per_month: float = 0.0
    doubling_time_days: Optional[float] = None  # For masses/nodules
    
    # Classification
    trend_classification: str = "stable"  # growing, shrinking, stable, new, resolved
    requires_followup: bool = False
    followup_interval_months: Optional[int] = None
    
    clinical_notes: str = ""


def calculate_vector_analysis(
    test_name: str,
    loinc_code: Optional[str],
    values: List[Tuple[datetime, float]],
    unit: str = ""
) -> VectorAnalysis:
    """
    Calculate comprehensive vector analysis for a series of lab values.
    
    Args:
        test_name: Name of the test
        loinc_code: LOINC code for per-test thresholds
        values: List of (datetime, value) tuples, sorted newest first
        unit: Unit of measurement
    
    Returns:
        VectorAnalysis with all calculated metrics
    """
    if not values:
        return VectorAnalysis(
            test_name=test_name,
            loinc_code=loinc_code,
            current_value=0,
            current_date=datetime.now(timezone.utc),
            unit=unit
        )
    
    # Sort by date (newest first)
    sorted_values = sorted(values, key=lambda x: x[0], reverse=True)
    
    analysis = VectorAnalysis(
        test_name=test_name,
        loinc_code=loinc_code,
        current_value=sorted_values[0][1],
        current_date=sorted_values[0][0],
        unit=unit,
        value_history=sorted_values
    )
    
    # Get per-test threshold
    threshold = get_rapid_change_threshold(loinc_code) if loinc_code else 20.0
    analysis.threshold_used = threshold
    
    if len(sorted_values) >= 2:
        analysis.previous_value = sorted_values[1][1]
        analysis.previous_date = sorted_values[1][0]
        analysis.oldest_value = sorted_values[-1][1]
        analysis.oldest_date = sorted_values[-1][0]
        
        # Calculate time span
        analysis.days_span = (analysis.current_date - analysis.oldest_date).days
        
        # Delta calculations
        if analysis.previous_value != 0:
            analysis.delta_absolute = analysis.current_value - analysis.previous_value
            analysis.delta_percent = (analysis.delta_absolute / abs(analysis.previous_value)) * 100
        
        if analysis.oldest_value != 0:
            total_delta = analysis.current_value - analysis.oldest_value
            analysis.total_delta_percent = (total_delta / abs(analysis.oldest_value)) * 100
        
        # Velocity calculation (rate of change)
        days_since_previous = (analysis.current_date - analysis.previous_date).days
        if days_since_previous > 0:
            analysis.velocity_per_day = analysis.delta_absolute / days_since_previous
            if analysis.previous_value != 0:
                analysis.velocity_percent_per_day = analysis.delta_percent / days_since_previous
        
        # Acceleration calculation (requires 3+ values)
        if len(sorted_values) >= 3:
            analysis.acceleration, analysis.acceleration_direction = _calculate_acceleration(sorted_values)
        
        # Statistical analysis
        numeric_values = [v[1] for v in sorted_values]
        analysis.mean_value = sum(numeric_values) / len(numeric_values)
        
        if len(numeric_values) >= 2:
            variance = sum((v - analysis.mean_value) ** 2 for v in numeric_values) / (len(numeric_values) - 1)
            analysis.std_deviation = math.sqrt(variance) if variance > 0 else 0
            
            if analysis.std_deviation > 0:
                analysis.z_score = (analysis.current_value - analysis.mean_value) / analysis.std_deviation
            
            if analysis.mean_value != 0:
                analysis.coefficient_of_variation = (analysis.std_deviation / abs(analysis.mean_value)) * 100
            
            # Statistical significance: z-score > 2 or CV > 15%
            analysis.is_statistically_significant = (
                abs(analysis.z_score) > 2.0 or 
                analysis.coefficient_of_variation > 15.0
            )
        
        # Determine rapid change flag using per-test threshold
        analysis.rapid_change_flag = abs(analysis.total_delta_percent) > threshold
        
        # Determine trend severity
        analysis.trend_severity = _classify_severity(analysis, threshold)
        
        # Add clinical notes with threshold source
        if loinc_code:
            test_config = get_threshold_for_test(loinc_code)
            source = get_threshold_source(loinc_code)
            notes_parts = []
            if test_config.clinical_notes:
                notes_parts.append(test_config.clinical_notes)
            notes_parts.append(f"Threshold: {source}")
            analysis.clinical_notes = ". ".join(notes_parts)
    
    return analysis


def _calculate_acceleration(values: List[Tuple[datetime, float]]) -> Tuple[float, str]:
    """
    Calculate acceleration (change in velocity) from a series of values.
    
    Returns:
        Tuple of (acceleration value, direction string)
    """
    if len(values) < 3:
        return 0.0, "stable"
    
    # Calculate velocities between consecutive points
    velocities = []
    for i in range(len(values) - 1):
        days = (values[i][0] - values[i+1][0]).days
        if days > 0:
            velocity = (values[i][1] - values[i+1][1]) / days
            velocities.append(velocity)
    
    if len(velocities) < 2:
        return 0.0, "stable"
    
    # Acceleration is change in velocity
    recent_velocity = velocities[0]
    older_velocity = velocities[-1]
    acceleration = recent_velocity - older_velocity
    
    # Determine direction
    if abs(acceleration) < 0.01:  # Threshold for "stable"
        direction = "stable"
    elif acceleration > 0:
        direction = "accelerating"  # Change is speeding up
    else:
        direction = "decelerating"  # Change is slowing down
    
    return acceleration, direction


def _classify_severity(analysis: VectorAnalysis, threshold: float) -> TrendSeverity:
    """Classify the severity of a trend based on multiple factors."""
    
    # Critical: Very large change OR statistically significant with rapid change
    if abs(analysis.total_delta_percent) > threshold * 2:
        return TrendSeverity.CRITICAL
    
    if analysis.rapid_change_flag and analysis.is_statistically_significant:
        return TrendSeverity.CRITICAL
    
    # Significant: Rapid change OR high z-score
    if analysis.rapid_change_flag:
        return TrendSeverity.SIGNIFICANT
    
    if abs(analysis.z_score) > 2.0:
        return TrendSeverity.SIGNIFICANT
    
    # Moderate: Notable change but not rapid
    if abs(analysis.total_delta_percent) > threshold * 0.5:
        return TrendSeverity.MODERATE
    
    # Minimal: Small change
    if abs(analysis.total_delta_percent) > 5:
        return TrendSeverity.MINIMAL
    
    return TrendSeverity.STABLE


def calculate_radiology_trend(
    patient_id: int,
    finding_type: str,
    body_region: str,
    measurements: List[Tuple[datetime, float, str]]
) -> RadiologyTrend:
    """
    Calculate trend for a radiology finding (e.g., nodule growth).
    
    Args:
        patient_id: Patient identifier
        finding_type: Type of finding (nodule, mass, etc.)
        body_region: Body region (lung, liver, etc.)
        measurements: List of (date, size_mm, notes) tuples
    
    Returns:
        RadiologyTrend with growth analysis
    """
    trend = RadiologyTrend(
        patient_id=patient_id,
        finding_type=finding_type,
        body_region=body_region,
        measurements=measurements
    )
    
    if len(measurements) < 2:
        trend.trend_classification = "new" if measurements else "unknown"
        return trend
    
    # Sort by date (newest first)
    sorted_measurements = sorted(measurements, key=lambda x: x[0], reverse=True)
    
    newest = sorted_measurements[0]
    oldest = sorted_measurements[-1]
    
    # Calculate size change
    if oldest[1] > 0:
        trend.size_change_percent = ((newest[1] - oldest[1]) / oldest[1]) * 100
    
    # Calculate growth rate (mm per month)
    days_span = (newest[0] - oldest[0]).days
    if days_span > 0:
        size_change_mm = newest[1] - oldest[1]
        trend.growth_rate_mm_per_month = (size_change_mm / days_span) * 30
        
        # Calculate doubling time for growing masses
        if trend.size_change_percent > 0 and oldest[1] > 0:
            # Doubling time = ln(2) / growth_rate
            # growth_rate = ln(newest/oldest) / days
            ratio = newest[1] / oldest[1]
            if ratio > 1:
                growth_rate = math.log(ratio) / days_span
                if growth_rate > 0:
                    trend.doubling_time_days = math.log(2) / growth_rate
    
    # Classify trend
    if newest[1] == 0 and oldest[1] > 0:
        trend.trend_classification = "resolved"
    elif trend.size_change_percent > 20:
        trend.trend_classification = "growing"
        trend.requires_followup = True
        trend.followup_interval_months = 3
    elif trend.size_change_percent < -20:
        trend.trend_classification = "shrinking"
        trend.requires_followup = True
        trend.followup_interval_months = 6
    else:
        trend.trend_classification = "stable"
        trend.followup_interval_months = 12
    
    # Add clinical notes based on finding type
    if finding_type.lower() in ["nodule", "mass"]:
        if trend.doubling_time_days and trend.doubling_time_days < 400:
            trend.clinical_notes = f"Doubling time {trend.doubling_time_days:.0f} days - concerning for malignancy"
            trend.requires_followup = True
            trend.followup_interval_months = 1
        elif trend.growth_rate_mm_per_month > 2:
            trend.clinical_notes = f"Growth rate {trend.growth_rate_mm_per_month:.1f} mm/month - needs close monitoring"
    
    return trend
