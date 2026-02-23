"""
LangGraph pipeline definition for medical report triage.
"""
import logging
from typing import Optional, Any
from functools import partial

from langgraph.graph import StateGraph, END

from .state import PipelineState
from .nodes import (
    intake_node,
    classify_node,
    extract_node,
    patient_context_node,
    historical_node,
    analyze_node,
    score_node,
    notify_node,
)

logger = logging.getLogger(__name__)


class TriagePipeline:
    """
    8-step medical report triage pipeline using LangGraph.
    
    Model Usage:
    - MedGemma 27B: Primary model for ALL text analysis (classification, extraction, analysis)
    - MedGemma 4B: ONLY for radiology image analysis (multimodal)
    
    Steps:
    1. Intake - Download content from S3
    2. Classify - Determine report type (27B model)
    3. Extract - Extract structured data (27B model)
    4. Patient Context - Fetch demographics
    5. Historical - Analyze trends
    6. Analyze - AI analysis (27B for text, 4B for radiology images only)
    7. Score - Calculate priority
    8. Notify - Send notifications
    """
    
    def __init__(
        self,
        aws_client: Any,
        mongodb_client: Any,
        redis_client: Any,
        medgemma_27b: Any,
        medgemma_4b: Any,
        loinc_client: Any,
        notification_service: Optional[Any] = None,
        pipeline_logger: Optional[Any] = None
    ):
        self.aws_client = aws_client
        self.mongodb_client = mongodb_client
        self.redis_client = redis_client
        self.medgemma_27b = medgemma_27b
        self.medgemma_4b = medgemma_4b
        self.loinc_client = loinc_client
        self.notification_service = notification_service
        self.pipeline_logger = pipeline_logger
        
        self._graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph pipeline."""
        
        # Create graph with state schema
        graph = StateGraph(PipelineState)
        
        # Add nodes with bound dependencies
        graph.add_node("intake", partial(
            intake_node,
            aws_client=self.aws_client,
            redis_client=self.redis_client,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("classify", partial(
            classify_node,
            medgemma_27b=self.medgemma_27b,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("extract", partial(
            extract_node,
            medgemma_27b=self.medgemma_27b,
            loinc_client=self.loinc_client,
            mongodb_client=self.mongodb_client,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("patient_context", partial(
            patient_context_node,
            mongodb_client=self.mongodb_client,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("historical", partial(
            historical_node,
            mongodb_client=self.mongodb_client,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("analyze", partial(
            analyze_node,
            medgemma_27b=self.medgemma_27b,
            medgemma_4b=self.medgemma_4b,
            mongodb_client=self.mongodb_client,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("score", partial(
            score_node,
            pipeline_logger=self.pipeline_logger
        ))
        
        graph.add_node("notify", partial(
            notify_node,
            notification_service=self.notification_service,
            mongodb_client=self.mongodb_client,
            pipeline_logger=self.pipeline_logger,
            medgemma_27b=self.medgemma_27b,
        ))
        
        # Define edges (linear flow)
        graph.set_entry_point("intake")
        graph.add_edge("intake", "classify")
        graph.add_edge("classify", "extract")
        graph.add_edge("extract", "patient_context")
        graph.add_edge("patient_context", "historical")
        graph.add_edge("historical", "analyze")
        graph.add_edge("analyze", "score")
        graph.add_edge("score", "notify")
        graph.add_edge("notify", END)
        
        return graph.compile()

    async def process_report(
        self,
        tenant_id: str,
        report_id: str,
        patient_id: int,
        report_type: str,
        pdf_url: Optional[str] = None,
        image_url: Optional[str] = None,
        report_date: Optional[str] = None,
        reporting_source: Optional[str] = None,
        is_final: bool = True
    ) -> PipelineState:
        """
        Process a single report through the pipeline.
        
        Args:
            tenant_id: Tenant identifier
            report_id: Unique report ID
            patient_id: Patient ID
            report_type: Type of report (lab, xray, ct, etc.)
            pdf_url: Pre-signed S3 URL for PDF
            image_url: Pre-signed S3 URL for image
            report_date: Report date string
            reporting_source: Source of the report
            is_final: Whether report is final
        
        Returns:
            Final pipeline state with all results
        """
        # Parse report_date string to datetime for type consistency
        from datetime import datetime, timezone
        parsed_date = None
        if report_date:
            try:
                parsed_date = datetime.fromisoformat(str(report_date).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                logger.warning(f"[{tenant_id}] Could not parse report_date '{report_date}', using current time")
                parsed_date = datetime.now(timezone.utc)
        
        # Initialize state
        initial_state: PipelineState = {
            "tenant_id": tenant_id,
            "report_id": report_id,
            "patient_id": patient_id,
            "report_type": report_type,
            "pdf_url": pdf_url,
            "image_url": image_url,
            "report_date": parsed_date,
            "reporting_source": reporting_source,
            "is_final": is_final,
            "errors": [],
            "step_timings": {},
            "extracted_lab_values": [],
            "loinc_mappings": {},
            "trends": [],
            "rapid_changes": [],
            "critical_trends": [],
            "findings": [],
            "recommendations": [],
            "notification_recipients": [],
            "image_observations": [],
            "image_abnormalities": False,
            "radiology_trends": [],
            "radiology_measurements": [],
        }
        
        logger.info(f"[{tenant_id}] Starting pipeline for report {report_id}")
        
        # Run the graph
        final_state = await self._graph.ainvoke(initial_state)
        
        return final_state
    
    def get_graph(self) -> StateGraph:
        """Get the compiled graph for visualization."""
        return self._graph


def create_triage_pipeline(
    aws_client: Any,
    mongodb_client: Any,
    redis_client: Any,
    medgemma_27b: Any,
    medgemma_4b: Any,
    loinc_client: Any,
    notification_service: Optional[Any] = None,
    pipeline_logger: Optional[Any] = None
) -> TriagePipeline:
    """
    Factory function to create a triage pipeline.
    
    Args:
        aws_client: AWS API client
        mongodb_client: MongoDB client
        redis_client: Redis client
        medgemma_27b: MedGemma 27B model client
        medgemma_4b: MedGemma 4B model client
        loinc_client: LOINC lookup client
        notification_service: Optional notification service
        pipeline_logger: Optional OpenSearch pipeline logger
    
    Returns:
        Configured TriagePipeline instance
    """
    return TriagePipeline(
        aws_client=aws_client,
        mongodb_client=mongodb_client,
        redis_client=redis_client,
        medgemma_27b=medgemma_27b,
        medgemma_4b=medgemma_4b,
        loinc_client=loinc_client,
        notification_service=notification_service,
        pipeline_logger=pipeline_logger
    )
