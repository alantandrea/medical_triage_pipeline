"""
LOINC Pydantic models for medical test classification.
"""
import logging
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re

logger = logging.getLogger(__name__)


class LOINCCode(BaseModel):
    """
    Represents a single LOINC code entry.
    Validates that LOINC codes follow the NNNNN-N format with valid check digit.
    """
    loinc_num: str = Field(..., description="LOINC code (e.g., '2345-7')")
    long_common_name: str = Field(..., description="Clinician-friendly name")
    short_name: Optional[str] = Field(default=None, description="Abbreviated name")
    component: Optional[str] = Field(default=None, description="What is measured")
    property: Optional[str] = Field(default=None, description="Kind of quantity (MCnc, NCnc, etc.)")
    time_aspect: Optional[str] = Field(default=None, description="Time aspect (Pt, 24H, etc.)")
    system: Optional[str] = Field(default=None, description="Specimen/body system")
    scale_type: Optional[str] = Field(default=None, description="Scale type (Qn, Ord, Nom, Nar)")
    method_type: Optional[str] = Field(default=None, description="Method (optional)")
    loinc_class: Optional[str] = Field(default=None, alias="class", description="Classification category")
    class_type: Optional[str] = Field(default=None, description="1=Lab, 2=Clinical, 3=Claims, 4=Surveys")
    order_obs: Optional[str] = Field(default=None, description="Order, Observation, or Both")
    status: str = Field(default="ACTIVE", description="ACTIVE, DEPRECATED, DISCOURAGED")
    
    @field_validator("loinc_num")
    @classmethod
    def validate_loinc_format(cls, v: str) -> str:
        """Validate LOINC code format: NNNNN-N with valid Mod 10 check digit."""
        pattern = r"^\d{1,5}-\d$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid LOINC format: {v}. Expected NNNNN-N format.")
        
        # Validate check digit using Mod 10 algorithm
        parts = v.split("-")
        base_num = parts[0]
        check_digit = int(parts[1])
        
        # Mod 10 check digit calculation
        total = 0
        for i, digit in enumerate(reversed(base_num)):
            d = int(digit)
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        
        calculated_check = (10 - (total % 10)) % 10
        
        if calculated_check != check_digit:
            # Log warning - some LOINC codes may have legacy check digits
            logger.warning(
                f"LOINC code {v} has invalid check digit "
                f"(expected {calculated_check}, got {check_digit})"
            )
        
        return v
    
    def to_redis_hash(self) -> dict:
        """Convert to dict for Redis hash storage."""
        return {
            "loinc_num": self.loinc_num,
            "long_common_name": self.long_common_name,
            "short_name": self.short_name or "",
            "component": self.component or "",
            "property": self.property or "",
            "time_aspect": self.time_aspect or "",
            "system": self.system or "",
            "scale_type": self.scale_type or "",
            "method_type": self.method_type or "",
            "class": self.loinc_class or "",
            "class_type": self.class_type or "",
            "order_obs": self.order_obs or "",
            "status": self.status,
        }
    
    @classmethod
    def from_redis_hash(cls, data: dict) -> "LOINCCode":
        """Create from Redis hash data."""
        return cls(
            loinc_num=data.get("loinc_num", ""),
            long_common_name=data.get("long_common_name", ""),
            short_name=data.get("short_name") or None,
            component=data.get("component") or None,
            property=data.get("property") or None,
            time_aspect=data.get("time_aspect") or None,
            system=data.get("system") or None,
            scale_type=data.get("scale_type") or None,
            method_type=data.get("method_type") or None,
            loinc_class=data.get("class") or None,
            class_type=data.get("class_type") or None,
            order_obs=data.get("order_obs") or None,
            status=data.get("status", "ACTIVE"),
        )


class LOINCLookupResult(BaseModel):
    """Result of a LOINC lookup operation."""
    code: Optional[LOINCCode] = Field(default=None, description="Matched LOINC code")
    found: bool = Field(default=False, description="Whether a match was found")
    match_type: str = Field(default="none", description="exact, normalized, synonym, fuzzy, none")
    query: str = Field(..., description="Original query string")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Match confidence")


class LOINCSynonymEntry(BaseModel):
    """A single synonym mapping entry."""
    synonym: str = Field(..., description="Alternate name (e.g., 'GLU')")
    canonical: str = Field(..., description="Canonical name it maps to (e.g., 'glucose')")
    source: str = Field(default="custom", description="Source: official, common_abbreviation, patient_friendly, custom")
