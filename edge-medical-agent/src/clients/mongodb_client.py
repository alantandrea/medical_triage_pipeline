"""
MongoDB async client for patient and lab data storage.
"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ..models import (
    Patient, StructuredLabValue, LabValueTrend, TrendDirection,
    VectorAnalysis, RadiologyTrend, calculate_vector_analysis, calculate_radiology_trend,
    get_rapid_change_threshold
)
from ..config import settings

logger = logging.getLogger(__name__)


class MongoDBClient:
    """Async MongoDB client for MedGemma Triage System."""
    
    def __init__(self, uri: Optional[str] = None, database: Optional[str] = None):
        self.uri = uri or settings.mongodb_uri
        self.database_name = database or settings.mongodb_database
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
    
    async def connect(self) -> None:
        """Establish MongoDB connection."""
        self._client = AsyncIOMotorClient(self.uri)
        self._db = self._client[self.database_name]
        # Create indexes
        await self._create_indexes()
        logger.info(f"Connected to MongoDB: {self.database_name}")
    
    async def close(self) -> None:
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
    
    async def _create_indexes(self) -> None:
        """Create necessary indexes for performance."""
        # Patients collection
        await self._db.patients.create_index("patient_id", unique=True)
        await self._db.patients.create_index("tenant_id")
        
        # Lab values collection
        await self._db.lab_values.create_index([
            ("tenant_id", 1), ("patient_id", 1), ("loinc_code", 1)
        ])
        await self._db.lab_values.create_index([
            ("tenant_id", 1), ("patient_id", 1), ("collection_date", -1)
        ])
        
        # Processed reports collection
        await self._db.processed_reports.create_index("report_id", unique=True)
        await self._db.processed_reports.create_index([
            ("tenant_id", 1), ("patient_id", 1)
        ])
        
        # Processed notes collection
        await self._db.processed_notes.create_index([
            ("tenant_id", 1), ("note_id", 1)
        ], unique=True)
        
        # Radiology findings collection (for trend tracking)
        await self._db.radiology_findings.create_index([
            ("tenant_id", 1), ("patient_id", 1), ("finding_type", 1), ("body_region", 1)
        ])
        await self._db.radiology_findings.create_index([
            ("tenant_id", 1), ("patient_id", 1), ("report_date", -1)
        ])

    # ==================== Patient Operations ====================
    
    async def upsert_patient(self, tenant_id: str, patient: Patient) -> None:
        """Insert or update a patient record."""
        doc = patient.model_dump()
        doc["tenant_id"] = tenant_id
        doc["synced_at"] = datetime.now(timezone.utc)
        
        await self._db.patients.update_one(
            {"tenant_id": tenant_id, "patient_id": patient.patient_id},
            {"$set": doc},
            upsert=True
        )
    
    async def get_patient(self, tenant_id: str, patient_id: int) -> Optional[Patient]:
        """Retrieve a patient by ID."""
        doc = await self._db.patients.find_one({
            "tenant_id": tenant_id,
            "patient_id": patient_id
        })
        if doc:
            return Patient(**doc)
        return None
    
    async def get_all_patients(self, tenant_id: str) -> List[Patient]:
        """Get all patients for a tenant."""
        cursor = self._db.patients.find({"tenant_id": tenant_id})
        patients = []
        async for doc in cursor:
            patients.append(Patient(**doc))
        return patients
    
    async def get_patient_count(self, tenant_id: str) -> int:
        """Get count of patients for a tenant."""
        return await self._db.patients.count_documents({"tenant_id": tenant_id})
    
    # ==================== Lab Value Operations ====================
    
    async def store_lab_value(self, lab_value: StructuredLabValue) -> None:
        """Store a structured lab value."""
        doc = lab_value.model_dump()
        await self._db.lab_values.insert_one(doc)
    
    async def store_lab_values_batch(self, lab_values: List[StructuredLabValue]) -> int:
        """Store multiple lab values in batch."""
        if not lab_values:
            return 0
        docs = [lv.model_dump() for lv in lab_values]
        result = await self._db.lab_values.insert_many(docs)
        return len(result.inserted_ids)
    
    async def get_patient_lab_history(
        self,
        tenant_id: str,
        patient_id: int,
        loinc_code: Optional[str] = None,
        test_name: Optional[str] = None,
        limit: int = 10
    ) -> List[StructuredLabValue]:
        """Get historical lab values for a patient."""
        query = {"tenant_id": tenant_id, "patient_id": patient_id}
        if loinc_code:
            query["loinc_code"] = loinc_code
        elif test_name:
            query["test_name"] = {"$regex": test_name, "$options": "i"}
        
        cursor = self._db.lab_values.find(query).sort(
            "collection_date", -1
        ).limit(limit)
        
        results = []
        async for doc in cursor:
            results.append(StructuredLabValue(**doc))
        return results

    async def get_lab_trend(
        self,
        tenant_id: str,
        patient_id: int,
        loinc_code: str,
        days: int = 30,
        max_values: int = 5
    ) -> LabValueTrend:
        """Calculate trend for a specific lab test (legacy method)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        cursor = self._db.lab_values.find({
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "loinc_code": loinc_code,
            "collection_date": {"$gte": cutoff}
        }).sort("collection_date", -1).limit(max_values)
        
        values = []
        test_name = ""
        async for doc in cursor:
            values.append((doc["collection_date"], doc["value"]))
            test_name = doc.get("test_name", "")
        
        # Calculate trend
        trend = LabValueTrend(
            test_name=test_name,
            loinc_code=loinc_code,
            values=values
        )
        
        if len(values) >= 2:
            oldest_val = values[-1][1]
            newest_val = values[0][1]
            
            if oldest_val != 0:
                delta = ((newest_val - oldest_val) / abs(oldest_val)) * 100
                trend.delta_percentage = delta
                
                # Use per-test threshold instead of global threshold
                threshold = get_rapid_change_threshold(loinc_code)
                
                if delta > threshold:
                    trend.trend_direction = TrendDirection.INCREASING
                    trend.rapid_change_flag = True
                elif delta < -threshold:
                    trend.trend_direction = TrendDirection.DECREASING
                    trend.rapid_change_flag = True
                elif delta > 5:
                    trend.trend_direction = TrendDirection.INCREASING
                elif delta < -5:
                    trend.trend_direction = TrendDirection.DECREASING
                else:
                    trend.trend_direction = TrendDirection.STABLE
        
        return trend

    async def get_enhanced_lab_trend(
        self,
        tenant_id: str,
        patient_id: int,
        loinc_code: str,
        days: int = 30,
        max_values: int = 10
    ) -> VectorAnalysis:
        """
        Calculate enhanced vector analysis for a specific lab test.
        
        Includes:
        - Per-test thresholds
        - Rate of change (velocity)
        - Acceleration
        - Statistical significance
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        cursor = self._db.lab_values.find({
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "loinc_code": loinc_code,
            "collection_date": {"$gte": cutoff}
        }).sort("collection_date", -1).limit(max_values)
        
        values = []
        test_name = ""
        unit = ""
        async for doc in cursor:
            values.append((doc["collection_date"], doc["value"]))
            test_name = doc.get("test_name", "")
            unit = doc.get("unit", "")
        
        return calculate_vector_analysis(
            test_name=test_name,
            loinc_code=loinc_code,
            values=values,
            unit=unit
        )

    # ==================== Radiology Trend Operations ====================

    async def store_radiology_finding(
        self,
        tenant_id: str,
        patient_id: int,
        finding_type: str,
        body_region: str,
        size_mm: float,
        report_date: datetime,
        notes: str = ""
    ) -> None:
        """Store a radiology finding measurement."""
        doc = {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "finding_type": finding_type,
            "body_region": body_region,
            "size_mm": size_mm,
            "report_date": report_date,
            "notes": notes,
            "created_at": datetime.now(timezone.utc)
        }
        await self._db.radiology_findings.insert_one(doc)

    async def get_radiology_trend(
        self,
        tenant_id: str,
        patient_id: int,
        finding_type: str,
        body_region: str,
        months: int = 24
    ) -> RadiologyTrend:
        """
        Calculate trend for a radiology finding (e.g., nodule growth).
        
        Args:
            tenant_id: Tenant identifier
            patient_id: Patient identifier
            finding_type: Type of finding (nodule, mass, etc.)
            body_region: Body region (lung, liver, etc.)
            months: How far back to look
        
        Returns:
            RadiologyTrend with growth analysis
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
        
        cursor = self._db.radiology_findings.find({
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "finding_type": finding_type,
            "body_region": body_region,
            "report_date": {"$gte": cutoff}
        }).sort("report_date", -1)
        
        measurements = []
        async for doc in cursor:
            measurements.append((
                doc["report_date"],
                doc["size_mm"],
                doc.get("notes", "")
            ))
        
        return calculate_radiology_trend(
            patient_id=patient_id,
            finding_type=finding_type,
            body_region=body_region,
            measurements=measurements
        )

    async def get_patient_radiology_findings(
        self,
        tenant_id: str,
        patient_id: int,
        months: int = 24
    ) -> list:
        """
        Get all radiology findings for a patient including notes text.

        Returns a list of dicts with finding_type, body_region, and notes
        so the tapestry can scan the notes for keywords (mass, cancer, etc.).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

        cursor = self._db.radiology_findings.find(
            {
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "report_date": {"$gte": cutoff},
            },
            {"_id": 0, "finding_type": 1, "body_region": 1, "notes": 1},
        ).sort("report_date", -1)

        results = []
        async for doc in cursor:
            results.append(doc)
        return results

    async def get_patient_report_findings(
        self,
        tenant_id: str,
        patient_id: int,
    ) -> List[str]:
        """
        Extract finding_notation strings from processed_reports for a patient.

        The processed_reports collection stores findings as:
            findings: [{finding_id, finding_notation, urgency_score}, ...]

        Returns a flat list of finding_notation strings so the tapestry
        can scan them for keywords (cancer, fracture, lymphoma, etc.).
        """
        cursor = self._db.processed_reports.find(
            {"tenant_id": tenant_id, "patient_id": patient_id},
            {"_id": 0, "findings": 1, "analysis_summary": 1},
        )

        notations: List[str] = []
        async for doc in cursor:
            for finding in doc.get("findings") or []:
                text = finding.get("finding_notation", "")
                if text:
                    notations.append(text)
            # Also include the analysis summary — MedGemma often puts
            # the most descriptive condition text here
            summary = doc.get("analysis_summary", "")
            if summary:
                notations.append(summary)
        return notations

    
    # ==================== Note Operations ====================

    async def store_note_result(
        self,
        tenant_id: str,
        note_id: str,
        patient_id: int,
        analysis: dict
    ) -> None:
        """Store processed note analysis result."""
        doc = {
            "tenant_id": tenant_id,
            "note_id": note_id,
            "patient_id": patient_id,
            "analysis": analysis,
            "processed_at": datetime.now(timezone.utc)
        }
        await self._db.processed_notes.update_one(
            {"tenant_id": tenant_id, "note_id": note_id},
            {"$set": doc},
            upsert=True
        )

    async def get_patient_note_summaries(
        self,
        tenant_id: str,
        patient_id: int,
        limit: int = 20,
    ) -> List[str]:
        """
        Get analysis summaries from processed clinical notes for a patient.

        Returns a list of summary strings from the analysis field.
        """
        cursor = self._db.processed_notes.find(
            {"tenant_id": tenant_id, "patient_id": patient_id},
            {"_id": 0, "analysis": 1},
        ).sort("processed_at", -1).limit(limit)

        summaries: List[str] = []
        async for doc in cursor:
            analysis = doc.get("analysis") or {}
            summary = analysis.get("summary", "")
            if summary:
                summaries.append(summary)
            # Also grab individual findings if present
            for f in analysis.get("findings", []):
                if isinstance(f, str) and f:
                    summaries.append(f)
                elif isinstance(f, dict):
                    text = f.get("finding_notation", "") or f.get("text", "")
                    if text:
                        summaries.append(text)
        return summaries

    # ==================== Report Tracking ====================
    
    async def mark_report_processed(
        self,
        tenant_id: str,
        report_id: str,
        patient_id: int,
        score: int,
        findings: List[dict],
        analysis_summary: str = "",
    ) -> None:
        """Record that a report has been processed."""
        doc = {
            "tenant_id": tenant_id,
            "report_id": report_id,
            "patient_id": patient_id,
            "score": score,
            "findings": findings,
            "analysis_summary": analysis_summary,
            "processed_at": datetime.now(timezone.utc)
        }
        await self._db.processed_reports.update_one(
            {"report_id": report_id},
            {"$set": doc},
            upsert=True
        )
    
    async def is_report_processed(self, report_id: str) -> bool:
        """Check if a report has already been processed."""
        doc = await self._db.processed_reports.find_one({"report_id": report_id})
        return doc is not None

    async def is_note_processed(self, tenant_id: str, note_id: str) -> bool:
        """Check if a note has already been processed."""
        doc = await self._db.processed_notes.find_one(
            {"tenant_id": tenant_id, "note_id": note_id}
        )
        return doc is not None


    async def get_patient_history(
        self,
        tenant_id: str,
        patient_id: int,
        exclude_report_id: str = None,
        limit: int = 10,
    ) -> list:
        """
        Fetch recent reports and notes for a patient, sorted newest-first.

        Returns a unified list of dicts with keys:
            type: "report" | "note"
            date: ISO datetime string
            score: int
            summary: str (first finding for reports, analysis summary for notes)
            item_id: report_id or note_id
        """
        history = []

        # Fetch recent reports
        report_filter = {"tenant_id": tenant_id, "patient_id": patient_id}
        if exclude_report_id:
            report_filter["report_id"] = {"$ne": exclude_report_id}

        cursor = self._db.processed_reports.find(
            report_filter, {"_id": 0}
        ).sort("processed_at", -1).limit(limit)
        async for doc in cursor:
            first_finding = ""
            if doc.get("findings"):
                first_finding = doc["findings"][0].get("finding_notation", "")
            history.append({
                "type": "report",
                "date": doc.get("processed_at", "").isoformat() if hasattr(doc.get("processed_at", ""), "isoformat") else str(doc.get("processed_at", "")),
                "score": doc.get("score", 0),
                "summary": first_finding,
                "item_id": doc.get("report_id", ""),
            })

        # Fetch recent notes
        note_cursor = self._db.processed_notes.find(
            {"tenant_id": tenant_id, "patient_id": patient_id}, {"_id": 0}
        ).sort("processed_at", -1).limit(limit)
        async for doc in note_cursor:
            analysis = doc.get("analysis", {})
            history.append({
                "type": "note",
                "date": doc.get("processed_at", "").isoformat() if hasattr(doc.get("processed_at", ""), "isoformat") else str(doc.get("processed_at", "")),
                "score": analysis.get("urgency_score", 0),
                "summary": analysis.get("summary", ""),
                "item_id": doc.get("note_id", ""),
            })

        # Sort combined list by date descending
        history.sort(key=lambda x: x["date"], reverse=True)
        return history[:limit]

    
    async def health_check(self) -> bool:
        """Check MongoDB connectivity."""
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False
