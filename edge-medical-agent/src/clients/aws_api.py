"""
AWS API client for fetching reports and patient data.
"""
import httpx
from typing import List, Optional
import logging

from ..models import Patient, PendingReport, PendingNote
from ..config import settings

logger = logging.getLogger(__name__)


class AWSAPIClient:
    """REST client for AWS backend API."""
    
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url or settings.aws_api_url
        self.api_key = api_key or settings.aws_api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        # Separate client for S3 downloads (PDFs + images) with longer timeout
        self.download_client = httpx.AsyncClient(timeout=120.0)
        
        # Add API key header if provided
        if self.api_key:
            self.client.headers["x-api-key"] = self.api_key
    
    async def close(self):
        """Close the HTTP clients."""
        await self.client.aclose()
        await self.download_client.aclose()
    
    async def get_pending_reports(self, limit: int = 50) -> List[PendingReport]:
        """Fetch unprocessed reports from AWS API."""
        try:
            response = await self.client.get(
                f"{self.base_url}/reports/pending",
                params={"limit": limit}
            )
            response.raise_for_status()
            data = response.json()
            return [PendingReport(**r) for r in data.get("pending_reports", [])]
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch pending reports: {e}")
            raise
    
    async def get_pending_notes(self, limit: int = 50) -> List[PendingNote]:
        """Fetch unprocessed patient notes from AWS API."""
        try:
            response = await self.client.get(
                f"{self.base_url}/notes/pending",
                params={"limit": limit}
            )
            response.raise_for_status()
            data = response.json()
            return [PendingNote(**n) for n in data.get("pending_notes", [])]
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch pending notes: {e}")
            raise
    
    async def get_patient(self, patient_id: int) -> Patient:
        """Fetch patient demographics."""
        try:
            response = await self.client.get(f"{self.base_url}/patients/{patient_id}")
            response.raise_for_status()
            data = response.json()
            return Patient(**data.get("patient", data))
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch patient {patient_id}: {e}")
            raise
    
    async def get_all_patients(self, limit: int = 1000) -> List[Patient]:
        """Fetch all patients for sync."""
        try:
            response = await self.client.get(
                f"{self.base_url}/patients",
                params={"limit": limit}
            )
            response.raise_for_status()
            data = response.json()
            return [Patient(**p) for p in data.get("patients", [])]
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch all patients: {e}")
            raise
    
    async def download_pdf(self, url: str) -> bytes:
        """Download PDF from pre-signed S3 URL (120s timeout)."""
        try:
            response = await self.download_client.get(url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            logger.error(f"Failed to download PDF: {e}")
            raise
    
    async def download_image(self, url: str) -> bytes:
        """Download image from pre-signed S3 URL (120s timeout)."""
        try:
            response = await self.download_client.get(url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            logger.error(f"Failed to download image: {e}")
            raise
    
    async def mark_report_processed(self, report_id: str) -> None:
        """Mark report as processed in AWS API.
        
        Non-fatal: logs errors but does not raise. The AWS PATCH /reports/update
        endpoint has a known bug (uses ScanCommand instead of QueryCommand) that
        returns 404 for valid report IDs. Pipeline results are still saved locally
        in MongoDB/OpenSearch regardless.
        """
        try:
            response = await self.client.patch(
                f"{self.base_url}/reports/update/{report_id}"
            )
            response.raise_for_status()
            logger.info(f"Marked report {report_id} as processed")
        except httpx.HTTPError as e:
            logger.warning(f"Could not mark report {report_id} as processed (non-fatal): {e}")
    
    async def mark_note_processed(self, note_id: str, result: dict) -> None:
        """Mark note as processed with AI results.
        
        Non-fatal: logs errors but does not raise. Pipeline results are still
        saved locally in MongoDB/OpenSearch regardless.
        """
        try:
            response = await self.client.patch(
                f"{self.base_url}/notes/update/{note_id}",
                json=result
            )
            response.raise_for_status()
            logger.info(f"Marked note {note_id} as processed")
        except httpx.HTTPError as e:
            logger.warning(f"Could not mark note {note_id} as processed (non-fatal): {e}")
    
    async def health_check(self) -> bool:
        """Check if AWS API is reachable."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False
