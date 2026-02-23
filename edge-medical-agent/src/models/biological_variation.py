"""
Biological Variation data loader for evidence-based Reference Change Values (RCV).

Source: Westgard Biological Variation Database (westgard.com/biodatabase1.htm)

RCV is the minimum percentage change between two consecutive lab results that is
statistically significant at 95% confidence, accounting for both analytical
imprecision (CVA) and within-subject biological variation (CVI).

Formula: RCV_95 = 1.96 * sqrt(2) * sqrt(CVA^2 + CVI^2)
       = 2.77 * sqrt(CVA^2 + CVI^2)

Where CVA (desirable analytical imprecision) = 0.5 * CVI per Westgard guidelines.
"""
import json
import logging
import math
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BiologicalVariationEntry(BaseModel):
    """A single analyte's biological variation data."""
    name: str
    specimen: str  # S=Serum, P=Plasma, B=Blood, U=Urine
    cvi: float     # Within-subject biological variation (%)
    cvg: float     # Between-subject biological variation (%)
    desirable_imprecision: float  # Desirable analytical CV (%)
    desirable_bias: float
    desirable_total_error: float
    rcv_95: float  # Pre-calculated RCV at 95% confidence (%)
    loinc_codes: list[str]


# Module-level lookup tables, populated on first access
_by_loinc: Dict[str, BiologicalVariationEntry] = {}
_by_name: Dict[str, BiologicalVariationEntry] = {}
_loaded: bool = False


def _load_data() -> None:
    """Load biological variation JSON data into lookup tables."""
    global _by_loinc, _by_name, _loaded
    if _loaded:
        return

    data_path = Path(__file__).resolve().parent.parent.parent / "data" / "biological_variation.json"
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        for item in raw.get("analytes", []):
            entry = BiologicalVariationEntry(**item)
            _by_name[entry.name.lower()] = entry
            for code in entry.loinc_codes:
                _by_loinc[code] = entry

        _loaded = True
        logger.info(f"Loaded biological variation data: {len(_by_name)} analytes, {len(_by_loinc)} LOINC mappings")
    except FileNotFoundError:
        logger.warning(f"Biological variation data not found at {data_path}")
        _loaded = True  # Don't retry on every call
    except Exception as e:
        logger.error(f"Failed to load biological variation data: {e}")
        _loaded = True


def get_rcv_by_loinc(loinc_code: str) -> Optional[float]:
    """Get the RCV (95% confidence) for a LOINC code. Returns None if not found."""
    _load_data()
    entry = _by_loinc.get(loinc_code)
    return entry.rcv_95 if entry else None


def get_entry_by_loinc(loinc_code: str) -> Optional[BiologicalVariationEntry]:
    """Get the full biological variation entry for a LOINC code."""
    _load_data()
    return _by_loinc.get(loinc_code)


def get_rcv_by_name(analyte_name: str) -> Optional[float]:
    """Get the RCV by analyte name (case-insensitive). Returns None if not found."""
    _load_data()
    entry = _by_name.get(analyte_name.lower())
    return entry.rcv_95 if entry else None


def get_entry_by_name(analyte_name: str) -> Optional[BiologicalVariationEntry]:
    """Get the full biological variation entry by analyte name."""
    _load_data()
    return _by_name.get(analyte_name.lower())


def compute_rcv(cvi: float, cva: Optional[float] = None, confidence: float = 0.95) -> float:
    """
    Compute RCV from CVI and CVA values.

    Args:
        cvi: Within-subject biological variation (%)
        cva: Analytical imprecision (%). Defaults to 0.5 * CVI (desirable).
        confidence: Confidence level (0.95 for 95%, 0.99 for 99%)

    Returns:
        RCV as a percentage
    """
    if cva is None:
        cva = 0.5 * cvi

    z = 1.96 if confidence >= 0.95 else 2.576 if confidence >= 0.99 else 1.645
    return z * math.sqrt(2) * math.sqrt(cva ** 2 + cvi ** 2)
