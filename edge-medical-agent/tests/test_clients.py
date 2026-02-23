"""
Tests for client modules.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.clients.aws_api import AWSAPIClient
from src.clients.mongodb_client import MongoDBClient
from src.clients.redis_client import RedisClient
from src.clients.medgemma_27b import MedGemma27BClient, AnalysisResult
from src.clients.medgemma_4b import MedGemma4BClient, ExtractionResult
from src.clients.loinc_client import LOINCClient


class TestAWSAPIClient:
    """Tests for AWS API client."""
    
    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """Test client initializes with default settings."""
        client = AWSAPIClient()
        assert client.base_url is not None
        await client.close()
    
    @pytest.mark.asyncio
    async def test_client_with_custom_url(self):
        """Test client with custom URL."""
        client = AWSAPIClient(base_url="https://custom.api.com")
        assert client.base_url == "https://custom.api.com"
        await client.close()


class TestMedGemma27BClient:
    """Tests for MedGemma 27B client."""
    
    def test_parse_analysis_response_complete(self):
        """Test parsing complete analysis response."""
        client = MedGemma27BClient()
        
        response = """SUMMARY: Elevated glucose levels detected
FINDINGS:
- Glucose at 126 mg/dL (high)
- HbA1c at 7.2% (elevated)
URGENCY_SCORE: 45
RECOMMENDATIONS:
- Review diabetes management
- Consider medication adjustment"""
        
        result = client._parse_analysis_response(response)
        
        assert result.summary == "Elevated glucose levels detected"
        assert len(result.findings) == 2
        assert result.urgency_score == 45
        assert len(result.recommendations) == 2
    
    def test_parse_analysis_response_missing_sections(self):
        """Test parsing response with missing sections."""
        client = MedGemma27BClient()
        
        response = """SUMMARY: Brief summary
URGENCY_SCORE: 30"""
        
        result = client._parse_analysis_response(response)
        
        assert result.summary == "Brief summary"
        assert result.urgency_score == 30
        assert result.findings == []
        assert result.recommendations == []
    
    def test_parse_analysis_response_invalid_score(self):
        """Test parsing response with invalid score defaults to 50."""
        client = MedGemma27BClient()
        
        response = """SUMMARY: Test
URGENCY_SCORE: invalid"""
        
        result = client._parse_analysis_response(response)
        assert result.urgency_score == 50
    
    def test_build_lab_prompt(self):
        """Test lab prompt building."""
        client = MedGemma27BClient()
        
        prompt = client._build_lab_prompt(
            report_text="Glucose: 126 mg/dL",
            patient_context="Age: 45, Sex: M",
            historical_context="Glucose trending up"
        )
        
        assert "Glucose: 126 mg/dL" in prompt
        assert "Age: 45" in prompt
        assert "trending up" in prompt


class TestMedGemma4BClient:
    """Tests for MedGemma 4B client."""
    
    def test_parse_extraction_response(self):
        """Test parsing extraction response."""
        client = MedGemma4BClient()
        
        response = """TEST: Glucose
VALUE: 126
UNIT: mg/dL
RANGE: 70-100
FLAG: HIGH
---
TEST: Hemoglobin A1c
VALUE: 7.2
UNIT: %
RANGE: 4.0-5.6
FLAG: HIGH
---"""
        
        result = client._parse_extraction_response(response)
        
        assert len(result.lab_values) == 2
        assert result.lab_values[0].test_name == "Glucose"
        assert result.lab_values[0].value == "126"
        assert result.lab_values[0].flag == "HIGH"
    
    def test_parse_extraction_response_empty(self):
        """Test parsing empty response."""
        client = MedGemma4BClient()
        
        result = client._parse_extraction_response("")
        assert result.lab_values == []


class TestLOINCClient:
    """Tests for LOINC client."""
    
    def test_normalize_name(self):
        """Test name normalization."""
        assert LOINCClient.normalize_name("Glucose") == "glucose"
        assert LOINCClient.normalize_name("Hemoglobin A1c") == "hemoglobin_a1c"
        assert LOINCClient.normalize_name("  Blood Sugar  ") == "blood_sugar"
        assert LOINCClient.normalize_name("C-Reactive Protein") == "c_reactive_protein"
    
    @pytest.mark.asyncio
    async def test_lookup_by_code_found(self, mock_redis_client, sample_loinc_code):
        """Test LOINC lookup by code when found."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = sample_loinc_code.to_redis_hash()
        
        client = LOINCClient(mock_redis, "test-tenant")
        result = await client.lookup_by_code("2345-7")
        
        assert result.found is True
        assert result.match_type == "exact"
        assert result.code.loinc_num == "2345-7"
    
    @pytest.mark.asyncio
    async def test_lookup_by_code_not_found(self):
        """Test LOINC lookup by code when not found."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        
        client = LOINCClient(mock_redis, "test-tenant")
        result = await client.lookup_by_code("9999-9")
        
        assert result.found is False
        assert result.match_type == "none"
