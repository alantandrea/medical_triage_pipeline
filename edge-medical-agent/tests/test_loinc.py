"""
Tests for LOINC ETL and administration.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
import tempfile
import os

from src.loinc.loader import LOINCLoader
from src.loinc.admin import LOINCAdmin
from src.models.loinc import LOINCCode


class TestLOINCLoader:
    """Tests for LOINC loader."""
    
    def test_normalize_name(self):
        """Test name normalization."""
        assert LOINCLoader.normalize_name("Glucose") == "glucose"
        assert LOINCLoader.normalize_name("Hemoglobin A1c") == "hemoglobin_a1c"
    
    @pytest.mark.asyncio
    async def test_load_synonyms(self):
        """Test loading synonyms from JSON."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipeline
        
        # Create temp synonyms file
        synonyms_data = {
            "synonyms": [
                {"synonym": "GLU", "canonical": "glucose", "source": "abbreviation"},
                {"synonym": "blood sugar", "canonical": "glucose", "source": "patient"}
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(synonyms_data, f)
            temp_path = f.name
        
        try:
            loader = LOINCLoader(mock_redis, "test-tenant")
            result = await loader.load_synonyms(temp_path)
            
            assert result["status"] == "completed"
            assert result["loaded"] == 2
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.asyncio
    async def test_check_data(self):
        """Test checking LOINC data status."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {
            "loaded_at": "2026-02-09T10:00:00",
            "source_file": "/path/to/Loinc.csv",
            "classes": "CHEM,HEM/BC"
        }
        
        # Mock scan_iter to return some keys
        async def mock_scan_iter(*args, **kwargs):
            for key in ["loinc:test:code:2345-7", "loinc:test:code:4548-4"]:
                yield key
        
        mock_redis.scan_iter = mock_scan_iter
        
        loader = LOINCLoader(mock_redis, "test-tenant")
        result = await loader.check_data()
        
        assert result["tenant_id"] == "test-tenant"
        assert result["code_count"] == 2


class TestLOINCAdmin:
    """Tests for LOINC admin."""
    
    @pytest.mark.asyncio
    async def test_add_code(self, sample_loinc_code):
        """Test adding a LOINC code."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipeline
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        result = await admin.add_code(sample_loinc_code)
        
        assert result is True
        mock_pipeline.hset.assert_called()
        mock_pipeline.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_remove_code(self, sample_loinc_code):
        """Test removing a LOINC code."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = sample_loinc_code.to_redis_hash()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipeline
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        result = await admin.remove_code("2345-7")
        
        assert result is True
        mock_pipeline.delete.assert_called()
    
    @pytest.mark.asyncio
    async def test_remove_code_not_found(self):
        """Test removing non-existent code."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        result = await admin.remove_code("9999-9")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_add_synonym(self):
        """Test adding a synonym."""
        mock_redis = AsyncMock()
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        result = await admin.add_synonym("GLU", "glucose")
        
        assert result is True
        mock_redis.set.assert_called()
    
    @pytest.mark.asyncio
    async def test_list_synonyms(self):
        """Test listing synonyms."""
        mock_redis = AsyncMock()
        
        async def mock_scan_iter(*args, **kwargs):
            yield "loinc:test:synonym:glu"
            yield "loinc:test:synonym:blood_sugar"
        
        mock_redis.scan_iter = mock_scan_iter
        mock_redis.get.side_effect = ["glucose", "glucose"]
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        synonyms = await admin.list_synonyms()
        
        assert len(synonyms) == 2
        assert synonyms[0]["canonical"] == "glucose"
    
    @pytest.mark.asyncio
    async def test_get_statistics(self):
        """Test getting statistics."""
        mock_redis = AsyncMock()
        
        # Mock scan_iter for codes
        code_keys = ["loinc:test:code:1", "loinc:test:code:2"]
        syn_keys = ["loinc:test:synonym:glu"]
        class_keys = ["loinc:test:class:CHEM"]
        
        call_count = [0]
        
        async def mock_scan_iter(match=None, **kwargs):
            if "code:" in match:
                for k in code_keys:
                    yield k
            elif "synonym:" in match:
                for k in syn_keys:
                    yield k
            elif "class:" in match:
                for k in class_keys:
                    yield k
        
        mock_redis.scan_iter = mock_scan_iter
        mock_redis.scard.return_value = 50
        mock_redis.hgetall.return_value = {"loaded_at": "2026-02-09"}
        
        admin = LOINCAdmin(mock_redis, "test-tenant")
        stats = await admin.get_statistics()
        
        assert stats["tenant_id"] == "test-tenant"
        assert stats["total_codes"] == 2
        assert stats["total_synonyms"] == 1
