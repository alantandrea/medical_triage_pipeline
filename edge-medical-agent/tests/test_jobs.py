"""
Tests for background jobs.
"""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from src.jobs.patient_sync import PatientSyncJob
from src.models import Patient


class TestPatientSyncJob:
    """Tests for patient sync job."""
    
    @pytest.mark.asyncio
    async def test_full_sync_success(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client,
        sample_patient
    ):
        """Test successful full sync."""
        # Setup mocks
        mock_aws_client.get_all_patients.return_value = [sample_patient]
        mock_mongodb_client.upsert_patient.return_value = None
        mock_redis_client.acquire_lock.return_value = True
        
        job = PatientSyncJob(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            tenant_id="test-tenant"
        )
        
        result = await job.run_full_sync()
        
        assert result["status"] == "completed"
        assert result["sync_type"] == "full"
        assert result["total_fetched"] == 1
        assert result["synced"] == 1
        assert result["errors"] == 0
    
    @pytest.mark.asyncio
    async def test_full_sync_lock_held(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client
    ):
        """Test sync skipped when lock is held."""
        mock_redis_client.acquire_lock.return_value = False
        
        job = PatientSyncJob(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            tenant_id="test-tenant"
        )
        
        result = await job.run_full_sync()
        
        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"
    
    @pytest.mark.asyncio
    async def test_full_sync_with_errors(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client,
        sample_patient
    ):
        """Test sync continues despite individual errors."""
        # Create two patients
        patient2 = Patient(
            patient_id=99999,
            first_name="Jane",
            last_name="Smith",
            patient_dob="1990-01-01",
            sex="F"
        )
        
        mock_aws_client.get_all_patients.return_value = [sample_patient, patient2]
        
        # First upsert succeeds, second fails
        mock_mongodb_client.upsert_patient.side_effect = [None, Exception("DB error")]
        mock_redis_client.acquire_lock.return_value = True
        
        job = PatientSyncJob(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            tenant_id="test-tenant"
        )
        
        result = await job.run_full_sync()
        
        assert result["status"] == "completed"
        assert result["total_fetched"] == 2
        assert result["synced"] == 1
        assert result["errors"] == 1
    
    @pytest.mark.asyncio
    async def test_incremental_sync(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client,
        sample_patient
    ):
        """Test incremental sync."""
        # Patient with recent update
        sample_patient.updated_at = datetime.utcnow()
        mock_aws_client.get_all_patients.return_value = [sample_patient]
        mock_redis_client.acquire_lock.return_value = True
        mock_redis_client.client.hgetall.return_value = {}
        
        job = PatientSyncJob(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            tenant_id="test-tenant"
        )
        
        result = await job.run_incremental_sync()
        
        assert result["status"] == "completed"
        assert result["sync_type"] == "incremental"
    
    @pytest.mark.asyncio
    async def test_get_status(
        self,
        mock_aws_client,
        mock_mongodb_client,
        mock_redis_client
    ):
        """Test getting sync status."""
        mock_mongodb_client.get_patient_count.return_value = 100
        mock_redis_client.client.hgetall.return_value = {
            "last_sync_time": "2026-02-09T10:00:00",
            "last_sync_type": "full",
            "last_synced": "100",
            "last_errors": "0",
            "last_duration": "5.5"
        }
        
        job = PatientSyncJob(
            aws_client=mock_aws_client,
            mongodb_client=mock_mongodb_client,
            redis_client=mock_redis_client,
            tenant_id="test-tenant"
        )
        
        status = await job.get_status()
        
        assert status["tenant_id"] == "test-tenant"
        assert status["patient_count"] == 100
        assert status["last_sync_type"] == "full"
