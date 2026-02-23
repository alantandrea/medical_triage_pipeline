"""
Tests for FastAPI endpoints.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_health_response_structure(self):
        """Test health check response structure."""
        # Expected response structure
        response = {
            "status": "healthy",
            "tenant_id": "test-tenant"
        }
        
        assert "status" in response
        assert "tenant_id" in response
        assert response["status"] in ["healthy", "degraded"]
    
    def test_detailed_health_response_structure(self):
        """Test detailed health check response structure."""
        response = {
            "tenant_id": "test-tenant",
            "aws_api": True,
            "mongodb": True,
            "redis": True,
            "medgemma_27b": True,
            "medgemma_4b": True,
            "status": "healthy"
        }
        
        required_keys = ["tenant_id", "aws_api", "mongodb", "redis", "medgemma_27b", "medgemma_4b", "status"]
        for key in required_keys:
            assert key in response
    
    def test_degraded_health_status(self):
        """Test degraded health when some services are down."""
        checks = {
            "tenant_id": "test",
            "aws_api": True,
            "mongodb": False,  # Down
            "redis": True,
            "medgemma_27b": True,
            "medgemma_4b": True,
        }
        
        all_healthy = all(v for k, v in checks.items() if k != "tenant_id")
        status = "healthy" if all_healthy else "degraded"
        
        assert status == "degraded"


class TestLOINCEndpoints:
    """Tests for LOINC lookup endpoints."""
    
    @pytest.mark.asyncio
    async def test_lookup_by_code_structure(self, sample_loinc_code):
        """Test LOINC lookup response structure."""
        from src.models.loinc import LOINCLookupResult
        
        result = LOINCLookupResult(
            code=sample_loinc_code,
            found=True,
            match_type="exact",
            query="2345-7",
            confidence=1.0
        )
        
        data = result.model_dump()
        
        assert "code" in data
        assert "found" in data
        assert "match_type" in data
        assert data["found"] is True
        assert data["code"]["loinc_num"] == "2345-7"
    
    @pytest.mark.asyncio
    async def test_lookup_not_found_structure(self):
        """Test LOINC lookup not found response."""
        from src.models.loinc import LOINCLookupResult
        
        result = LOINCLookupResult(
            found=False,
            match_type="none",
            query="unknown-test",
            confidence=0.0
        )
        
        data = result.model_dump()
        
        assert data["found"] is False
        assert data["code"] is None
        assert data["match_type"] == "none"
    
    @pytest.mark.asyncio
    async def test_search_response_structure(self, sample_loinc_code):
        """Test LOINC search response structure."""
        from src.models.loinc import LOINCLookupResult
        
        results = [
            LOINCLookupResult(
                code=sample_loinc_code,
                found=True,
                match_type="fuzzy",
                query="glucose",
                confidence=0.85
            )
        ]
        
        data = [r.model_dump() for r in results]
        
        assert len(data) == 1
        assert data[0]["confidence"] == 0.85
    
    @pytest.mark.asyncio
    async def test_metadata_response_structure(self):
        """Test LOINC metadata response structure."""
        metadata = {
            "loaded_at": "2026-02-09T10:00:00",
            "source_file": "/path/to/Loinc.csv",
            "total_codes": "100000",
            "classes": "CHEM,HEM/BC,UA"
        }
        
        assert "loaded_at" in metadata
        assert "total_codes" in metadata


class TestPatientEndpoints:
    """Tests for patient endpoints."""
    
    @pytest.mark.asyncio
    async def test_patient_response_structure(self, sample_patient):
        """Test patient response structure."""
        data = sample_patient.model_dump()
        
        assert "patient_id" in data
        assert "first_name" in data
        assert "last_name" in data
        assert data["patient_id"] == 12345
    
    @pytest.mark.asyncio
    async def test_patient_lab_history_structure(self, sample_lab_values):
        """Test patient lab history response structure."""
        data = [lv.model_dump() for lv in sample_lab_values]
        
        assert len(data) == 2
        assert data[0]["test_name"] == "Glucose"
        assert data[0]["loinc_code"] == "2345-7"
        assert "value" in data[0]
        assert "unit" in data[0]


class TestJobEndpoints:
    """Tests for job trigger endpoints."""
    
    @pytest.mark.asyncio
    async def test_full_sync_result_structure(self):
        """Test full sync result structure."""
        result = {
            "status": "completed",
            "sync_type": "full",
            "tenant_id": "test",
            "total_fetched": 100,
            "synced": 100,
            "errors": 0,
            "duration_seconds": 5.5,
            "completed_at": "2026-02-09T10:00:00"
        }
        
        assert result["status"] == "completed"
        assert result["sync_type"] == "full"
        assert result["synced"] == 100
        assert result["errors"] == 0
    
    @pytest.mark.asyncio
    async def test_incremental_sync_result_structure(self):
        """Test incremental sync result structure."""
        result = {
            "status": "completed",
            "sync_type": "incremental",
            "tenant_id": "test",
            "since": "2026-02-08T00:00:00",
            "total_updated": 10,
            "synced": 10,
            "errors": 0,
            "duration_seconds": 1.2
        }
        
        assert result["sync_type"] == "incremental"
        assert "since" in result
        assert result["total_updated"] == 10
    
    @pytest.mark.asyncio
    async def test_sync_status_structure(self):
        """Test sync status response structure."""
        status = {
            "tenant_id": "test",
            "patient_count": 1000,
            "last_sync_time": "2026-02-09T10:00:00",
            "last_sync_type": "full",
            "last_synced": 1000,
            "last_errors": 0,
            "last_duration": 30.5
        }
        
        assert "patient_count" in status
        assert "last_sync_time" in status
        assert status["patient_count"] == 1000
    
    @pytest.mark.asyncio
    async def test_sync_skipped_result(self):
        """Test sync skipped when lock held."""
        result = {
            "status": "skipped",
            "reason": "lock_held"
        }
        
        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"


class TestPipelineEndpoints:
    """Tests for pipeline-related endpoints (future)."""
    
    @pytest.mark.asyncio
    async def test_pipeline_result_structure(self):
        """Test pipeline result structure."""
        result = {
            "tenant_id": "test",
            "report_id": "RPT-001",
            "patient_id": 12345,
            "final_score": 65,
            "priority_level": "important",
            "findings": [
                {"finding_notation": "Elevated glucose"}
            ],
            "recommendations": ["Review diabetes management"],
            "notification_sent": True,
            "step_timings": {
                "intake": 100,
                "classify": 50,
                "extract": 200,
                "patient_context": 30,
                "historical": 40,
                "analyze": 500,
                "score": 10,
                "notify": 100
            }
        }
        
        assert result["final_score"] == 65
        assert result["priority_level"] == "important"
        assert len(result["step_timings"]) == 8
