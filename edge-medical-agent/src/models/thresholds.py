"""
Per-test clinical thresholds for rapid change detection.

Different lab tests have different clinical significance for the same percentage change.
For example, a 20% change in glucose is less concerning than a 20% change in creatinine.

Where available, thresholds are derived from evidence-based Reference Change Values (RCV)
using biological variation data from the Westgard database (westgard.com/biodatabase1.htm).
The RCV represents the minimum change between two consecutive results that is statistically
significant at 95% confidence, accounting for both analytical and biological variation.

For tests without biological variation data, hardcoded clinical thresholds are used as fallback.
"""
import logging
from typing import Dict, Optional
from pydantic import BaseModel

from .biological_variation import get_rcv_by_loinc, get_entry_by_loinc

logger = logging.getLogger(__name__)


class TestThreshold(BaseModel):
    """Threshold configuration for a specific lab test."""
    loinc_code: str
    test_name: str
    rapid_change_percent: float  # Hardcoded fallback threshold
    critical_high: Optional[float] = None  # Critical high value
    critical_low: Optional[float] = None  # Critical low value
    unit: str = ""
    clinical_notes: str = ""


# Per-test thresholds based on clinical significance
# Lower threshold = more sensitive to changes (more clinically significant)
LAB_THRESHOLDS: Dict[str, TestThreshold] = {
    # Kidney Function - very sensitive to changes
    "2160-0": TestThreshold(
        loinc_code="2160-0",
        test_name="Creatinine",
        rapid_change_percent=15.0,  # 15% change is significant
        critical_high=10.0,
        critical_low=0.2,
        unit="mg/dL",
        clinical_notes="Acute kidney injury if >0.3 mg/dL increase in 48h"
    ),
    "3094-0": TestThreshold(
        loinc_code="3094-0",
        test_name="BUN",
        rapid_change_percent=25.0,
        critical_high=100.0,
        unit="mg/dL",
        clinical_notes="Elevated in dehydration, kidney disease, GI bleeding"
    ),
    "33914-3": TestThreshold(
        loinc_code="33914-3",
        test_name="eGFR",
        rapid_change_percent=15.0,
        critical_low=15.0,
        unit="mL/min/1.73m2",
        clinical_notes="<15 indicates kidney failure"
    ),
    
    # Electrolytes - critical for cardiac function
    "2823-3": TestThreshold(
        loinc_code="2823-3",
        test_name="Potassium",
        rapid_change_percent=10.0,  # Very sensitive
        critical_high=6.5,
        critical_low=2.5,
        unit="mEq/L",
        clinical_notes="Cardiac arrhythmia risk at extremes"
    ),
    "2951-2": TestThreshold(
        loinc_code="2951-2",
        test_name="Sodium",
        rapid_change_percent=8.0,  # Very sensitive
        critical_high=160.0,
        critical_low=120.0,
        unit="mEq/L",
        clinical_notes="Rapid correction can cause osmotic demyelination"
    ),
    "17861-6": TestThreshold(
        loinc_code="17861-6",
        test_name="Calcium",
        rapid_change_percent=15.0,
        critical_high=13.0,
        critical_low=6.0,
        unit="mg/dL",
        clinical_notes="Hypercalcemia can cause cardiac issues"
    ),
    
    # Glucose - moderate sensitivity
    "2345-7": TestThreshold(
        loinc_code="2345-7",
        test_name="Glucose",
        rapid_change_percent=30.0,  # Higher threshold - glucose varies
        critical_high=500.0,
        critical_low=40.0,
        unit="mg/dL",
        clinical_notes="Fasting glucose; varies with meals"
    ),
    "4548-4": TestThreshold(
        loinc_code="4548-4",
        test_name="Hemoglobin A1c",
        rapid_change_percent=15.0,
        critical_high=14.0,
        unit="%",
        clinical_notes="Reflects 3-month average glucose"
    ),
    
    # Liver Function
    "1742-6": TestThreshold(
        loinc_code="1742-6",
        test_name="ALT",
        rapid_change_percent=50.0,  # Can vary significantly
        critical_high=1000.0,
        unit="U/L",
        clinical_notes="Acute hepatitis if >10x upper limit"
    ),
    "1920-8": TestThreshold(
        loinc_code="1920-8",
        test_name="AST",
        rapid_change_percent=50.0,
        critical_high=1000.0,
        unit="U/L",
        clinical_notes="Also elevated in cardiac/muscle injury"
    ),
    "1975-2": TestThreshold(
        loinc_code="1975-2",
        test_name="Bilirubin Total",
        rapid_change_percent=25.0,
        critical_high=15.0,
        unit="mg/dL",
        clinical_notes="Jaundice visible >2.5 mg/dL"
    ),
    
    # Hematology
    "718-7": TestThreshold(
        loinc_code="718-7",
        test_name="Hemoglobin",
        rapid_change_percent=15.0,
        critical_high=20.0,
        critical_low=7.0,
        unit="g/dL",
        clinical_notes="Transfusion typically considered <7 g/dL"
    ),
    "4544-3": TestThreshold(
        loinc_code="4544-3",
        test_name="Hematocrit",
        rapid_change_percent=15.0,
        critical_high=60.0,
        critical_low=20.0,
        unit="%",
        clinical_notes="Correlates with hemoglobin"
    ),
    "777-3": TestThreshold(
        loinc_code="777-3",
        test_name="Platelets",
        rapid_change_percent=30.0,
        critical_high=1000.0,
        critical_low=20.0,
        unit="x10^3/uL",
        clinical_notes="Bleeding risk <50, spontaneous bleeding <20"
    ),
    "6690-2": TestThreshold(
        loinc_code="6690-2",
        test_name="WBC",
        rapid_change_percent=40.0,
        critical_high=30.0,
        critical_low=2.0,
        unit="x10^3/uL",
        clinical_notes="Infection, leukemia, or immunosuppression"
    ),
    
    # Cardiac Markers - very sensitive
    "10839-9": TestThreshold(
        loinc_code="10839-9",
        test_name="Troponin I",
        rapid_change_percent=20.0,
        critical_high=0.04,
        unit="ng/mL",
        clinical_notes="Any elevation suggests myocardial injury"
    ),
    "33762-6": TestThreshold(
        loinc_code="33762-6",
        test_name="NT-proBNP",
        rapid_change_percent=30.0,
        critical_high=900.0,
        unit="pg/mL",
        clinical_notes="Heart failure marker"
    ),
    
    # Thyroid
    "3016-3": TestThreshold(
        loinc_code="3016-3",
        test_name="TSH",
        rapid_change_percent=50.0,  # TSH varies widely
        critical_high=100.0,
        critical_low=0.01,
        unit="mIU/L",
        clinical_notes="Wide normal range; interpret with T4"
    ),
    
    # Prostate
    "2857-1": TestThreshold(
        loinc_code="2857-1",
        test_name="PSA",
        rapid_change_percent=25.0,
        critical_high=10.0,
        unit="ng/mL",
        clinical_notes="Velocity >0.75 ng/mL/year concerning"
    ),
    
    # Coagulation
    "5902-2": TestThreshold(
        loinc_code="5902-2",
        test_name="PT",
        rapid_change_percent=20.0,
        critical_high=50.0,
        unit="seconds",
        clinical_notes="Bleeding risk if prolonged"
    ),
    "6301-6": TestThreshold(
        loinc_code="6301-6",
        test_name="INR",
        rapid_change_percent=20.0,
        critical_high=5.0,
        unit="ratio",
        clinical_notes="Therapeutic range 2-3 for most indications"
    ),
}

# Default threshold for tests not in the list
DEFAULT_THRESHOLD = TestThreshold(
    loinc_code="default",
    test_name="Default",
    rapid_change_percent=20.0,
    clinical_notes="Default threshold for unlisted tests"
)


def get_threshold_for_test(loinc_code: str) -> TestThreshold:
    """Get the threshold configuration for a specific test."""
    return LAB_THRESHOLDS.get(loinc_code, DEFAULT_THRESHOLD)


def get_rapid_change_threshold(loinc_code: str) -> float:
    """
    Get the rapid change percentage threshold for a test.

    Priority:
    1. Evidence-based RCV from Westgard biological variation data (95% confidence)
    2. Hardcoded per-test threshold from LAB_THRESHOLDS
    3. Default 20%
    """
    # Try evidence-based RCV first
    rcv = get_rcv_by_loinc(loinc_code)
    if rcv is not None:
        return round(rcv, 2)

    # Fall back to hardcoded threshold
    return get_threshold_for_test(loinc_code).rapid_change_percent


def get_threshold_source(loinc_code: str) -> str:
    """
    Return the source of the threshold used for a given LOINC code.

    Returns one of:
    - "RCV (Westgard biological variation, 95% confidence)"
    - "Hardcoded clinical threshold"
    - "Default threshold"
    """
    rcv = get_rcv_by_loinc(loinc_code)
    if rcv is not None:
        entry = get_entry_by_loinc(loinc_code)
        return f"RCV {rcv:.1f}% (Westgard BV: CVI={entry.cvi}%, CVA={entry.desirable_imprecision}%)"

    if loinc_code in LAB_THRESHOLDS:
        return "Hardcoded clinical threshold"

    return "Default threshold (20%)"
