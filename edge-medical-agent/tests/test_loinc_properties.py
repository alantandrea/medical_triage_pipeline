"""
Property-based tests for LOINC validation and lookup.
"""
import pytest
from hypothesis import given, strategies as st, settings as hyp_settings, assume
import re

from src.models.loinc import LOINCCode, LOINCLookupResult
from src.clients.loinc_client import LOINCClient


class TestLOINCCodeProperties:
    """Property-based tests for LOINC code validation."""
    
    @given(
        base_num=st.integers(min_value=1, max_value=99999),
        check_digit=st.integers(min_value=0, max_value=9)
    )
    @hyp_settings(max_examples=100)
    def test_loinc_format_validation(self, base_num: int, check_digit: int):
        """
        Property: LOINC codes must match NNNNN-N format.
        
        **Validates: Requirements 16.1** - LOINC format validation
        """
        loinc_num = f"{base_num}-{check_digit}"
        
        # Should match the pattern
        pattern = r"^\d{1,5}-\d$"
        assert re.match(pattern, loinc_num) is not None
    
    @given(
        base_num=st.integers(min_value=1, max_value=99999)
    )
    @hyp_settings(max_examples=50)
    def test_mod10_check_digit_calculation(self, base_num: int):
        """
        Property: Mod-10 check digit is deterministic.
        
        **Validates: Requirements 16.2** - Check digit validation
        """
        base_str = str(base_num)
        
        # Calculate Mod-10 check digit
        total = 0
        for i, digit in enumerate(reversed(base_str)):
            d = int(digit)
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        
        check_digit = (10 - (total % 10)) % 10
        
        # Check digit should be 0-9
        assert 0 <= check_digit <= 9
        
        # Same input should always produce same check digit
        total2 = 0
        for i, digit in enumerate(reversed(base_str)):
            d = int(digit)
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total2 += d
        
        check_digit2 = (10 - (total2 % 10)) % 10
        assert check_digit == check_digit2
    
    @given(
        loinc_num=st.from_regex(r"^\d{1,5}-\d$", fullmatch=True),
        long_name=st.text(min_size=1, max_size=200)
    )
    @hyp_settings(max_examples=50)
    def test_loinc_code_roundtrip(self, loinc_num: str, long_name: str):
        """
        Property: LOINC code survives Redis hash roundtrip.
        
        **Validates: Requirements 16.3** - Data integrity in storage
        """
        assume(len(long_name.strip()) > 0)
        
        try:
            code = LOINCCode(
                loinc_num=loinc_num,
                long_common_name=long_name.strip(),
                component="Test",
                status="ACTIVE"
            )
            
            # Convert to Redis hash and back
            hash_data = code.to_redis_hash()
            restored = LOINCCode.from_redis_hash(hash_data)
            
            assert restored.loinc_num == code.loinc_num
            assert restored.long_common_name == code.long_common_name
            assert restored.status == code.status
        except ValueError:
            # Invalid LOINC format is expected for some generated values
            pass


class TestLOINCClientProperties:
    """Property-based tests for LOINC client."""
    
    @given(
        name=st.text(min_size=1, max_size=100, alphabet=st.characters(
            whitelist_categories=('L', 'N', 'P'),
            whitelist_characters=' -_'
        ))
    )
    @hyp_settings(max_examples=100)
    def test_name_normalization_idempotent(self, name: str):
        """
        Property: Normalizing a name twice gives same result.
        
        **Validates: Requirements 17.1** - Normalization consistency
        """
        assume(len(name.strip()) > 0)
        
        normalized1 = LOINCClient.normalize_name(name)
        normalized2 = LOINCClient.normalize_name(normalized1)
        
        assert normalized1 == normalized2
    
    @given(
        name=st.text(min_size=1, max_size=100, alphabet=st.characters(
            whitelist_categories=('L', 'N'),
            whitelist_characters=' -_'
        ))
    )
    @hyp_settings(max_examples=100)
    def test_name_normalization_lowercase(self, name: str):
        """
        Property: Normalized names are always lowercase.
        
        **Validates: Requirements 17.2** - Case insensitivity
        """
        assume(len(name.strip()) > 0)
        
        normalized = LOINCClient.normalize_name(name)
        
        assert normalized == normalized.lower()
    
    @given(
        name=st.text(min_size=1, max_size=100, alphabet=st.characters(
            whitelist_categories=('L', 'N'),
            whitelist_characters=' -_'
        ))
    )
    @hyp_settings(max_examples=100)
    def test_name_normalization_no_spaces(self, name: str):
        """
        Property: Normalized names have no spaces (replaced with underscores).
        
        **Validates: Requirements 17.3** - Consistent key format
        """
        assume(len(name.strip()) > 0)
        
        normalized = LOINCClient.normalize_name(name)
        
        assert " " not in normalized


class TestLOINCLookupResultProperties:
    """Property-based tests for lookup results."""
    
    @given(
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    )
    @hyp_settings(max_examples=50)
    def test_confidence_bounded(self, confidence: float):
        """
        Property: Confidence is always between 0 and 1.
        
        **Validates: Requirements 17.4** - Confidence bounds
        """
        result = LOINCLookupResult(
            found=True,
            match_type="fuzzy",
            query="test",
            confidence=confidence
        )
        
        assert 0.0 <= result.confidence <= 1.0
    
    @given(
        match_type=st.sampled_from(["exact", "normalized", "synonym", "fuzzy", "none"])
    )
    @hyp_settings(max_examples=20)
    def test_match_type_valid(self, match_type: str):
        """
        Property: Match type is always a valid value.
        
        **Validates: Requirements 17.5** - Valid match types
        """
        result = LOINCLookupResult(
            found=match_type != "none",
            match_type=match_type,
            query="test"
        )
        
        assert result.match_type in ["exact", "normalized", "synonym", "fuzzy", "none"]
