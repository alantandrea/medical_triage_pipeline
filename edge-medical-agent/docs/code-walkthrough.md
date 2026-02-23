# MedGemma Triage System - Code Walkthrough

This document provides a comprehensive walkthrough of the MedGemma Triage System codebase. It is designed to assist with code review by explaining each component, its purpose, and how it integrates with the overall system. No code snippets are included; instead, this document references the actual source files for detailed examination.

## Table of Contents

1. Project Overview
2. Directory Structure
3. Entry Points and Configuration
4. Data Models
5. External Clients
6. The LangGraph Pipeline
7. Pipeline Nodes (Step by Step)
8. Scheduler and Worker Architecture
9. Supporting Services
10. OpenSearch Pipeline Logging
11. Kubernetes Deployment
12. Testing Infrastructure
13. Deployment Procedures
14. Kaggle Challenge Submission

---

## 1. Project Overview

The MedGemma Triage System is an AI-powered medical report triage application designed for primary care practices. It automatically processes incoming lab reports, radiology images, pathology reports, and patient notes, assigning priority scores and alerting clinical staff to urgent findings.

The system uses two MedGemma models with distinct roles. MedGemma 27B IT serves as the primary text analysis engine, handling all classification, extraction, and clinical assessment tasks. MedGemma 4B IT is used exclusively for radiology image analysis due to its multimodal capabilities with MedSigLIP.

The architecture follows a microservices pattern with three main components: a scheduler that polls for new reports, a worker that processes reports through an eight-step LangGraph pipeline, and an API that provides REST endpoints for manual operations and health checks.

---

## 2. Directory Structure

The codebase is organized into the following structure within the medical-agent folder.

The root level contains the main entry point in main.py, the Dockerfile for containerization, requirements.txt for Python dependencies, and deploy.sh for automated deployment. The .env.example file shows all configurable environment variables.

The src folder contains all application source code, organized into subfolders for clients, jobs, loinc, models, pipeline, reporting, scheduler, and worker. The config.py file at the src root defines all configuration settings using Pydantic.

The k8s folder contains Kubernetes manifests for deploying the system to a K3s cluster. The data folder contains LOINC reference data including a synonyms.json file for test name mapping, and biological variation data from the Westgard database for evidence-based Reference Change Values. The docs folder contains documentation including this walkthrough. The tests folder contains the test suite with unit tests and property-based tests.

---

## 3. Entry Points and Configuration

### Main Application Entry Point

Reference file: main.py

The main.py file is the primary entry point for the FastAPI application. It initializes all client connections during startup using an async context manager for proper lifecycle management. The application exposes health check endpoints, patient sync job triggers, LOINC lookup endpoints, and patient data retrieval endpoints.

During startup, the application creates instances of all required clients including the AWS API client, MongoDB client, Redis client, both MedGemma model clients, and the LOINC lookup client. These are stored in a global AppState object and properly closed during shutdown.

### Configuration Settings

Reference file: src/config.py

All configuration is managed through a Pydantic Settings class that reads from environment variables with sensible defaults. The configuration includes tenant identification, AWS API connection details, scheduler timing parameters, model server URLs, infrastructure connection strings for Redis and MongoDB, notification thresholds for different priority levels, email settings, vector analysis parameters, and LOINC configuration options.

The settings object is instantiated once and imported throughout the codebase, ensuring consistent configuration access.

### Environment Variables

Reference file: .env.example

This file documents all available environment variables. Key variables include TENANT_ID for multi-tenant support, AWS_API_URL for the backend service, MEDGEMMA_27B_URL and MEDGEMMA_4B_URL for model server endpoints, REDIS_URL and MONGODB_URI for infrastructure, and various threshold settings for scoring and notifications.

---

## 4. Data Models

### Core Schemas

Reference file: src/models/schemas.py

This file defines the Pydantic models used throughout the system. The Patient model represents patient demographics synced from the AWS API. The PendingReport model represents reports fetched from the pending queue, including the report type, severity, and pre-signed S3 URLs for PDF and image content. The PendingNote model represents patient notes with pre-extracted vitals.

The PatientReport model is used for in-flight report state stored in Redis during processing. The ReportFinding model represents individual findings discovered during analysis. The StructuredLabValue model is used for storing normalized lab values in MongoDB with LOINC codes.

The LabValueTrend model represents trend information for a single lab test, including the direction of change and whether a rapid change was detected. The TrendDirection enum defines the possible trend states: increasing, decreasing, stable, or unknown.

### LOINC Models

Reference file: src/models/loinc.py

This file defines models for LOINC code handling. The LOINCCode model represents a single LOINC entry with validation of the code format and check digit. The validator logs warnings for invalid check digits rather than failing, as some legacy codes may have incorrect digits.

The LOINCLookupResult model wraps lookup results with metadata about match type and confidence. The LOINCSynonymEntry model represents synonym mappings for test name resolution.

### Clinical Thresholds

Reference file: src/models/thresholds.py

This file defines per-test clinical thresholds for rapid change detection. Different lab tests have different clinical significance for the same percentage change. For example, a ten percent change in potassium is more concerning than a thirty percent change in glucose.

The file contains a dictionary of TestThreshold objects keyed by LOINC code, covering kidney function tests, electrolytes, glucose, liver function, hematology, cardiac markers, thyroid, prostate, and coagulation tests. Each threshold includes the rapid change percentage, critical high and low values, units, and clinical notes.

The get_rapid_change_threshold function uses a priority-based lookup. It first checks the Westgard biological variation database for an evidence-based Reference Change Value (RCV) at 95% confidence. If found, the RCV is used as the threshold. If no biological variation data exists for that LOINC code, it falls back to the hardcoded per-test threshold or the default 20%. The get_threshold_source function returns a human-readable string describing which source was used, including the CVI and CVA values when RCV-based.

### Biological Variation Data

Reference file: src/models/biological_variation.py
Data file: data/biological_variation.json

This module provides evidence-based Reference Change Values derived from the Westgard Biological Variation Database. The RCV is the minimum percentage change between two consecutive lab results that is statistically significant at 95% confidence, accounting for both analytical imprecision and within-subject biological variation.

The JSON data file contains approximately 55 analytes covering all common primary care lab tests. Each entry includes the within-subject biological variation (CVI), between-subject variation (CVG), desirable analytical imprecision, and a pre-calculated RCV at 95% confidence. LOINC code mappings connect the analyte names to the codes used throughout the pipeline.

The loader reads the JSON file once on first access and builds two lookup dictionaries: one keyed by LOINC code and one by analyte name. Functions include get_rcv_by_loinc, get_rcv_by_name, get_entry_by_loinc, get_entry_by_name, and compute_rcv for calculating RCV from arbitrary CVI and CVA values.

### Vector Analysis

Reference file: src/models/vector_analysis.py

This file provides enhanced vector analysis for lab values and radiology findings. The VectorAnalysis class contains comprehensive metrics including velocity (rate of change per day), acceleration (whether the change is speeding up or slowing down), statistical measures like z-score and coefficient of variation, and clinical interpretation including trend severity classification.

The TrendSeverity enum defines five levels: critical, significant, moderate, minimal, and stable. The classification considers multiple factors including the magnitude of change relative to per-test thresholds, statistical significance, and acceleration.

The RadiologyTrend class tracks imaging findings over time, calculating size change percentage, growth rate in millimeters per month, and doubling time for masses and nodules. This is critical for malignancy assessment.

The calculate_vector_analysis function takes a series of lab values and returns a complete VectorAnalysis object. It uses get_rapid_change_threshold which automatically selects the evidence-based RCV when available. The clinical_notes field on each analysis includes the threshold source so downstream consumers can see whether the threshold was RCV-based or hardcoded. The calculate_radiology_trend function does the same for imaging findings.

### Model Exports

Reference file: src/models/__init__.py

This file exports all model classes and functions from the models subpackage, providing a clean import interface for the rest of the application.

---

## 5. External Clients

### AWS API Client

Reference file: src/clients/aws_api.py

This client communicates with the AWS backend service that provides mock medical reports for testing. It uses httpx for async HTTP requests. Key methods include get_pending_reports for fetching unprocessed reports, get_pending_notes for fetching patient notes, get_patient and get_all_patients for demographics, download_pdf and download_image for fetching content from pre-signed S3 URLs, and mark_report_processed and mark_note_processed for updating processing status.

### MongoDB Client

Reference file: src/clients/mongodb_client.py

This client handles all MongoDB operations using the Motor async driver. It manages patient records, lab value storage, processed report tracking, radiology finding storage, and clinical note storage.

Key methods include upsert_patient and get_patient for patient management, store_lab_value and store_lab_values_batch for lab data, get_patient_lab_history for retrieving historical values, get_lab_trend for basic trend calculation, and get_enhanced_lab_trend for comprehensive vector analysis.

The client includes methods for radiology trend tracking: store_radiology_finding, get_radiology_trend, and get_patient_radiology_findings which returns individual finding documents with finding_type, body_region, and notes fields (using find() instead of aggregation to preserve the notes text for tapestry keyword scanning).

For the Patient Tapestry, the client provides get_patient_report_findings which extracts finding_notation strings and analysis_summary text from the processed_reports collection, and get_patient_note_summaries which pulls analysis summaries and individual findings from the processed_notes collection. These methods feed the tapestry's data gathering pipeline.

The mark_report_processed method accepts an optional analysis_summary parameter (default empty string) which is stored alongside findings in the processed_reports collection. This allows the tapestry to access the AI's analysis summary for each historical report.

The get_patient_history method returns a unified list of recent reports and notes sorted by date, used for both email patient history tables and tapestry data gathering. Database indexes are created automatically on connection for optimal query performance.

### Redis Client

Reference file: src/clients/redis_client.py

This client manages Redis operations for in-flight report state, findings storage, and distributed locking. It uses the redis-py async client.

Key methods include store_report_state and get_report_state for managing report processing state, add_finding and get_findings for accumulating findings during pipeline execution, and acquire_lock and release_lock for distributed coordination between scheduler instances.

### MedGemma 27B Client

Reference file: src/clients/medgemma_27b.py

This client communicates with the MedGemma 27B IT model server. The 27B model is text-only and serves as the primary analysis engine for all text-based tasks.

Key methods include analyze_lab_report for comprehensive lab report analysis, synthesize_radiology_findings for combining 4B image findings with clinical context, analyze_radiology_text for text-only radiology report analysis, classify_report_type for determining report category, and extract_lab_values for structured data extraction.

The client also includes classify_tapestry_regions, which accepts a compiled patient summary and asks MedGemma 27B to identify all affected body regions for the Patient Tapestry visualization. The prompt describes all 20 valid body regions with detailed coverage descriptions, severity levels (caution, abnormal, critical), and special flags (is_mass for tumors/cancer, is_anatomical for fractures/hemorrhages). The model returns a JSON array which is validated by _parse_tapestry_response — invalid regions are filtered out, markdown code fences are stripped, and severity values are normalized.

Each method builds an appropriate prompt, sends it to the model server via the OpenAI-compatible chat completions API, and parses the structured response. The client includes response parsing logic that extracts summary, findings, urgency score, and recommendations from the model output.

### MedGemma 4B Client

Reference file: src/clients/medgemma_4b.py

This client communicates with the MedGemma 4B IT model server. The 4B model has multimodal capabilities through MedSigLIP and is used exclusively for radiology image analysis.

The key method is analyze_radiology_image, which takes image bytes and returns textual findings. These findings are then passed to the 27B model for clinical synthesis. The extract_radiology_measurements method takes the textual findings and extracts structured measurements (finding type, body region, size in millimeters) for storage in MongoDB and trend tracking. The client also includes extract_lab_values and classify_report_type methods for fast text processing, and extract_patient_vitals for parsing vital signs from patient notes.

### LOINC Client

Reference file: src/clients/loinc_client.py

This client provides LOINC code lookups using Redis as the backing store. It supports exact code lookup, normalized name lookup, synonym resolution, and optional fuzzy matching using rapidfuzz.

The lookup_by_name method tries multiple strategies in order: direct normalized name match, synonym lookup, and fuzzy matching if enabled. The search method returns multiple potential matches for a query. The client uses Redis hash structures for efficient storage and retrieval.

### Client Exports

Reference file: src/clients/__init__.py

This file exports all client classes from the clients subpackage.

### OpenSearch Pipeline Logger

Reference file: src/clients/opensearch_client.py

The PipelineLogger class provides a common logging library that every pipeline node calls to write structured documents to OpenSearch. Each call to log_step indexes one document capturing what a pipeline step did, its key outputs, errors, and timing. Documents are fire-and-forget — failures are logged but never block the pipeline.

The logger connects to OpenSearch using the opensearch-py async client. It uses daily index rotation with the pattern pipeline-logs-YYYY.MM.DD. Each document includes a timestamp, tenant and report identifiers, the step name, a one-line synopsis, optional details dictionary, error message if the step failed, duration in milliseconds, and the current priority level and final score from the pipeline state.

The log_event method provides a convenience API for logging non-pipeline events such as scheduler skips, worker starts, and backpressure activations.

The PipelineLogger is instantiated in the pipeline worker during startup, connected via an async connect call, and injected into all eight pipeline nodes through functools.partial in the graph builder. If OpenSearch is unreachable, the logger silently disables itself and the pipeline continues without logging.

---

## 6. The LangGraph Pipeline

### Pipeline Definition

Reference file: src/pipeline/graph.py

The TriagePipeline class defines the eight-step LangGraph pipeline for medical report processing. The pipeline is constructed using LangGraph's StateGraph with nodes for each processing step connected in a linear flow.

The constructor takes all required client dependencies and stores them for injection into pipeline nodes. The _build_graph method creates the graph structure, adding nodes with bound dependencies using functools.partial.

The process_report method is the main entry point for processing a single report. It initializes the pipeline state with input parameters and invokes the graph asynchronously. The method returns the final state containing all processing results.

The create_triage_pipeline factory function provides a convenient way to instantiate the pipeline with all dependencies.

### Pipeline State

Reference file: src/pipeline/state.py

The PipelineState TypedDict defines all fields that flow through the pipeline. Fields are organized by pipeline step and include input identifiers, raw content bytes, classification results, extraction results, patient context, historical analysis, AI analysis results, scoring, notification status, and metadata including timing and errors.

The state is passed through each node, with nodes reading their required inputs and writing their outputs. This provides a clean data flow model with explicit dependencies between steps.

### Node Exports

Reference file: src/pipeline/nodes/__init__.py

This file exports all pipeline node functions from the nodes subpackage.

---

## 7. Pipeline Nodes (Step by Step)

### Step 1: Intake

Reference file: src/pipeline/nodes/intake.py

The intake node downloads report content from S3 using pre-signed URLs. It retrieves the PDF document and, for radiology reports, the associated image. The node detects image format by examining the file header bytes.

Inputs: pdf_url, image_url from state
Outputs: pdf_bytes, image_bytes, image_format, processing_started timestamp

### Step 2: Classify

Reference file: src/pipeline/nodes/classify.py

The classify node determines the report type and extracts text from the PDF. It uses pypdf to extract text content, then calls the MedGemma 27B model to classify the report if the type is not already known.

The node emphasizes that MedGemma 27B handles all text analysis and routing decisions. MedGemma 4B is only used for radiology image analysis.

Inputs: pdf_bytes, report_type from state
Outputs: classified_type, extracted_text

### Step 3: Extract

Reference file: src/pipeline/nodes/extract.py

The extract node extracts structured lab values from the report text and maps them to LOINC codes. It uses MedGemma 27B for extraction, then looks up each test name in the LOINC client to find the corresponding code.

Inputs: extracted_text, classified_type from state
Outputs: extracted_lab_values (list of structured values), loinc_mappings (test name to LOINC code dictionary)

### Step 4: Patient Context

Reference file: src/pipeline/nodes/patient_context.py

The patient context node fetches patient demographics from MongoDB to provide context for analysis. It retrieves the patient record and builds a context string containing age and sex, which are relevant for interpreting lab values.

The node is careful not to log PHI (Protected Health Information) while still providing useful debugging information.

Inputs: patient_id, tenant_id from state
Outputs: patient_name, patient_dob, patient_context (formatted string)

### Step 5: Historical Analysis

Reference file: src/pipeline/nodes/historical.py

The historical node analyzes trends in lab values over time using the enhanced vector analysis system. For each extracted lab value with a LOINC code, it retrieves historical values and calculates comprehensive trend metrics.

The node uses per-test thresholds for clinically meaningful change detection. It tracks critical trends separately from significant changes and builds a formatted context string with severity indicators for the AI model.

For radiology reports (xray, ct, mri, mra, pet), the node also performs radiology trend analysis. It queries MongoDB for prior radiology findings for the patient, groups them by finding type and body region, and calculates growth trends using the RadiologyTrend model from vector_analysis.py. Growing findings with rapid doubling times (under 400 days) are flagged as critical trends. Other growing findings are added to significant changes. Shrinking and stable findings are noted in the context string. This radiology trend data flows into the score node for proportional scoring.

Inputs: extracted_lab_values, patient_id, tenant_id, classified_type from state
Outputs: trends (list of trend data), rapid_changes (list of test names), critical_trends (list of test names), historical_context (formatted string), radiology_trends (list of radiology trend data)

### Step 6: AI Analysis

Reference file: src/pipeline/nodes/analyze.py

The analyze node performs comprehensive AI analysis using the appropriate MedGemma model based on report type. For radiology reports, it implements a two-stage workflow: first using MedGemma 4B to analyze the image and generate textual findings, then using MedGemma 27B to synthesize those findings with clinical context.

When the 4B model detects abnormalities in a radiology image, the analyze node also extracts structured measurements (finding type, body region, size in millimeters) using a follow-up prompt to the 4B model. These measurements are stored in MongoDB via store_radiology_finding, building the historical record that the historical node uses for radiology trend tracking on subsequent reports.

For text-only reports like labs and pathology, it uses MedGemma 27B directly. The node includes graceful fallback to text-only analysis if no image is available for radiology reports.

Inputs: classified_type, extracted_text, image_bytes, image_format, patient_context, historical_context from state
Outputs: analysis_summary, findings (list), urgency_score (0-100), recommendations (list), image_findings (for radiology), radiology_measurements (structured measurements stored in MongoDB)

### Step 7: Score

Reference file: src/pipeline/nodes/score.py

The score node calculates the final priority score by combining multiple factors. It starts with the AI urgency score and adds bonuses for critical trends, significant changes, statistical significance, critical lab values, report type, and radiology growth.

The radiology growth bonus uses proportional scoring based on clinical significance. Findings with doubling times under 400 days (concerning for malignancy) receive the highest bonus. Findings growing faster than 2mm per month receive a moderate bonus. Other growing findings receive a smaller bonus. The radiology growth bonus is capped at 40 points.

The scoring formula provides transparency through a detailed breakdown stored in the state. The final score is capped at 100 and mapped to a priority level: routine, followup, important, or urgent.

Inputs: urgency_score, critical_trends, rapid_changes, trends, extracted_lab_values, classified_type, radiology_trends from state
Outputs: final_score (0-100), priority_level, score_breakdown (detailed component breakdown including radiology_growth_bonus)

### Step 8: Notify

Reference file: src/pipeline/nodes/notify.py

The notify node sends notifications based on priority level and persists results to MongoDB. Urgent reports trigger immediate email alerts to the clinical team. Important reports receive standard email notifications. Followup reports are queued for daily digest. Routine reports are simply persisted without notification.

The node accepts an optional medgemma_27b parameter (injected via functools.partial in graph.py) and passes it through to the notification service for Patient Tapestry generation. It also passes the analysis_summary from the pipeline state to mark_report_processed, ensuring the AI's summary is stored in MongoDB for future tapestry lookups.

The node marks the report as processed in MongoDB and records the total processing time.

Inputs: final_score, priority_level, findings, recommendations, patient context from state
Outputs: notification_sent, notification_type, notification_recipients, processing_completed timestamp

---

## 8. Scheduler and Worker Architecture

### Report Poller (Scheduler)

Reference file: src/scheduler/report_poller.py

The ReportPoller class implements APScheduler-based polling for pending reports and notes. It runs as a separate pod in the Kubernetes deployment, polling the AWS API at configurable intervals (default 60 seconds).

The poller includes a backpressure mechanism that prevents queue overload. At the start of each poll cycle, it checks the combined depth of the report and note Redis queues against a configurable threshold (QUEUE_BACKPRESSURE_THRESHOLD, default 20). If the total queue depth meets or exceeds the threshold, the poll is skipped entirely and a log message is emitted. The scheduler continues running on its normal interval, so the next poll cycle will automatically re-check the queue depth. Once the worker drains enough items from the queues, the depth drops below the threshold and polling resumes. This self-regulating loop prevents overwhelming the model servers and pipeline when processing is slow or backed up.

The poller also uses a Redis distributed lock to ensure only one instance polls at a time, preventing duplicate processing if multiple scheduler replicas are accidentally deployed. When reports or notes are found, they are serialized to JSON and pushed to Redis queues using LPUSH for FIFO ordering.

The main function sets up signal handlers for graceful shutdown and runs the poller in an async event loop.

### Pipeline Worker

Reference file: src/worker/pipeline_worker.py

The PipelineWorker class consumes reports and notes from Redis queues and processes them through the LangGraph pipeline. It runs as a separate pod with configurable concurrency (default 1 to avoid race conditions on model servers).

The worker loop continuously checks the Redis queues using RPOP, processing reports with priority over notes. For reports, it invokes the full LangGraph pipeline. For notes, it uses a simplified text-only flow with MedGemma 27B.

After processing, the worker marks items as processed in the AWS API and logs results. The main function handles signal-based shutdown similar to the scheduler.

---

## 9. Supporting Services

### Patient Sync Job

Reference file: src/jobs/patient_sync.py

The PatientSyncJob class synchronizes patient demographics from the AWS API to local MongoDB. It supports both full sync (all patients) and incremental sync (only changed patients). The job tracks sync status in Redis and provides status reporting.

### LOINC Data Management

Reference files: src/loinc/loader.py, src/loinc/etl_job.py, src/loinc/admin.py

The LOINC module handles loading and managing LOINC reference data. The loader reads LOINC data files and populates Redis with code entries, name indexes, and synonym mappings. The ETL job orchestrates the loading process. The admin module provides utilities for managing LOINC data.

### Notification Service

Reference file: src/reporting/service.py

The NotificationService class handles sending email notifications for urgent and important findings. It uses aiosmtplib for async email delivery and supports different notification templates based on priority level.

Both send_urgent_alert and send_important_notification accept an optional medgemma_27b parameter which is passed to the tapestry generator. When TAPESTRY_ENABLED is true and a mongodb_client and tenant_id are available, the service calls generate_tapestry to produce an inline SVG body map that is embedded directly in the HTML email. If tapestry generation fails for any reason, the email is sent without it.

The service also includes a patient history table builder that renders recent reports and notes with color-coded scores in the email body.

### Patient Tapestry

Reference file: src/reporting/tapestry.py

The tapestry module generates a color-coded SVG human body visualization for patient emails. It provides an instant visual overview of which body systems are affected.

The generate_tapestry function is the main entry point. It accepts mongodb_client, tenant_id, patient_id, and an optional medgemma_27b client. The primary path uses MedGemma 27B to classify affected regions from the full patient record. The fallback path uses keyword-based classification if the model is unavailable.

The _gather_patient_summary function compiles data from five MongoDB sources: abnormal lab values, radiology findings with notes, processed report findings and analysis summaries, patient history, and clinical notes from processed_notes. This compiled text is sent to MedGemma 27B's classify_tapestry_regions method.

The _build_svg function renders the three visual areas: on-body organ ellipses (7 regions on the silhouette), spine vertebrae (16 segments), and body systems grid (12 circles in a 4x3 layout). Each region is colored by severity, with red X icons for masses/tumors and orange triangles for anatomical findings.

The _keyword_fallback function provides classification when MedGemma is unavailable, using LAB_TO_REGION (120+ lab test mappings), RADIOLOGY_REGION_NORMALISE, and keyword dictionaries for region detection, mass detection, and anatomical finding detection.

### LOINC Synonyms Data

Reference file: data/loinc/synonyms.json

This JSON file contains synonym mappings for common lab test names. It maps abbreviations and alternate names to canonical LOINC test names, enabling flexible test name resolution.

---

## 10. OpenSearch Pipeline Logging

Every pipeline node writes a structured document to OpenSearch after completing its work. This creates a complete flow trace for each report that can be queried and visualized in OpenSearch Dashboards.

### How It Works

The PipelineLogger is created in the pipeline worker during startup. It connects to OpenSearch using the OPENSEARCH_URL from configuration (default http://localhost:9200, NodePort 30920 on the K3s cluster). If OpenSearch is unreachable, the logger disables itself silently and the pipeline runs without logging.

The logger is injected into all eight pipeline nodes via functools.partial in graph.py. Each node calls pipeline_logger.log_step after completing its work, passing the current pipeline state, the step name, a one-line synopsis of what happened, an optional details dictionary with key outputs, and the step duration in milliseconds. On errors, the node passes the error message instead.

### Index Pattern

Documents are written to daily-rotated indexes following the pattern pipeline-logs-YYYY.MM.DD. This allows easy retention management and time-based queries in OpenSearch Dashboards.

### Document Structure

Each document contains a timestamp, tenant_id, report_id, patient_id, report_type, step name, synopsis, details, error (if any), duration_ms, priority_level, and final_score. The priority_level and final_score fields are populated as the pipeline progresses, so early steps will have null values for these fields.

### Querying Flow Logs

To trace a single report through the pipeline, query by report_id and sort by timestamp. This shows every step the report went through, what each step produced, how long it took, and whether any errors occurred. This is invaluable for debugging model reasoning, understanding why a report received a particular score, and identifying performance bottlenecks.

### Non-Pipeline Events

The log_event method allows the scheduler and worker to log events outside the pipeline, such as backpressure skips, worker startup, and queue drain events. These use the same daily index pattern.

---

## 11. Kubernetes Deployment

### Namespace

Reference file: k8s/namespace.yaml

Defines the medgemma-triage namespace for isolating all system resources.

### ConfigMap

Reference file: k8s/configmap.yaml

Contains all non-sensitive configuration values including tenant ID, API URLs, model server endpoints, infrastructure connection strings, scoring thresholds, and LOINC settings. Note that model servers are accessed via localhost because pods use host networking.

### Secrets

Reference file: k8s/secrets.yaml.example

Template for sensitive configuration including API keys, SMTP credentials, and notification email addresses. This file should be copied to secrets.yaml and populated with actual values before deployment.

### Scheduler Deployment

Reference file: k8s/scheduler-deployment.yaml

Deploys the report scheduler as a single replica (to avoid duplicate polling). Uses host networking to access model servers on the host. Runs the scheduler module directly via Python.

### Worker Deployment

Reference file: k8s/worker-deployment.yaml

Deploys the pipeline worker as a single replica (to avoid race conditions on model servers). Uses host networking for model server access. Runs the worker module directly via Python.

### API Deployment

Reference file: k8s/api-deployment.yaml

Deploys the FastAPI application with two replicas for horizontal scaling. Does not require host networking. Includes a NodePort service exposing port 30800 for external access. Includes liveness and readiness probes for health monitoring.

### Infrastructure Deployments

Reference files: k8s/redis.yaml, k8s/mongodb.yaml

Deploy Redis and MongoDB as single-replica stateful services within the cluster. These are accessed by application pods via Kubernetes service DNS names.

---

## 12. Testing Infrastructure

### Test Configuration

Reference file: pytest.ini

Configures pytest with async support, test discovery patterns, and coverage reporting.

### Test Fixtures

Reference file: tests/conftest.py

Provides shared fixtures for tests including mock clients, sample data, and test configuration.

### Unit Tests

Reference files: tests/test_models.py, tests/test_clients.py, tests/test_pipeline.py, tests/test_api.py, tests/test_loinc.py, tests/test_jobs.py, tests/test_reporting.py

These files contain unit tests for each component of the system. Tests use pytest-asyncio for async testing and mock external dependencies.

### Property-Based Tests

Reference files: tests/test_loinc_properties.py, tests/test_scoring_properties.py

These files contain property-based tests using the Hypothesis library. Property-based tests verify that invariants hold across a wide range of generated inputs, providing stronger guarantees than example-based tests.

### Integration Tests

Reference file: tests/test_integration.py

Contains integration tests that verify end-to-end functionality with real or mock external services.

### Test Runner

Reference file: run_tests.py

Convenience script for running the test suite with appropriate configuration.

### Import Verification

Reference file: test_imports.py

Verifies that all modules can be imported without errors, catching import-time issues early.

---

## 13. Deployment Procedures

### Prerequisites

Before deployment, ensure the following are in place on the DGX Spark server:

The K3s cluster must be running with kubectl configured. MongoDB, Redis, and OpenSearch pods should be deployed and healthy. MedGemma 27B must be running on port 8357 using the HuggingFace server (not containerized due to GB10 GPU requirements). MedGemma 4B must be running on port 8358.

### Automated Deployment

Reference file: deploy.sh

The deploy.sh script automates the deployment process. It builds the Docker image for ARM64 architecture, saves it to a tar file, copies it to the Spark server via SCP, imports it into K3s using the container runtime, copies Kubernetes manifests, and applies them to the cluster.

The script can be run with the --skip-build flag to skip image building and only update manifests.

### Manual Deployment Steps

For manual deployment or troubleshooting, follow these steps:

First, build the Docker image locally using docker buildx for ARM64 architecture. Save the image to a tar file using docker save. Copy the tar file to the Spark server using SCP. SSH to the Spark server and import the image using sudo k3s ctr images import.

Copy the k8s folder to the server. Apply manifests in order: namespace, infrastructure (redis, mongodb), configmap, secrets, then application deployments (scheduler, worker, api).

Verify deployment using kubectl get pods to check pod status and kubectl logs to examine pod output.

### Configuration Updates

To update configuration without rebuilding the image, edit the configmap.yaml file and apply it using kubectl apply. Then restart the affected pods using kubectl rollout restart deployment.

For secret updates, edit secrets.yaml and apply similarly. Pods will automatically pick up new secret values on restart.

### Scaling

The API deployment can be scaled horizontally by increasing the replica count. The scheduler should remain at one replica to avoid duplicate polling. The worker can potentially be scaled if model servers can handle concurrent requests, but this requires careful testing.

---

## 14. Kaggle Challenge Submission

### Submission Requirements

For the Kaggle MedGemma Impact Challenge, the submission should demonstrate the complete system including the AI-powered triage pipeline, integration with MedGemma models, and practical deployment on edge infrastructure.

### Packaging the Submission

The submission package should include the complete medical-agent codebase with all source files, the documentation in the docs folder including this walkthrough, the Kubernetes manifests for reproducible deployment, sample test data and expected outputs, and a README explaining how to run the system.

### Key Differentiators to Highlight

The submission should emphasize the dual-model architecture with intelligent routing between 27B and 4B models, the comprehensive vector analysis for clinically meaningful trend detection, the evidence-based Reference Change Values from the Westgard biological variation database for scientifically grounded rapid change thresholds, the production-ready microservices architecture, and the edge deployment capability on DGX Spark.

### Demo Preparation

For the demo, prepare sample reports covering different types (lab, radiology, pathology) and severities (normal through critical). Show the complete flow from report arrival through notification. Demonstrate the vector analysis with historical data showing trend detection. Highlight the two-stage radiology workflow with image analysis followed by clinical synthesis.

### Documentation to Include

Include this code walkthrough, the architecture diagram from architecture.md, the deployment guide from deploy.md, the test plan from test-plan.md, and the runbook from runbook.md for operational procedures.

---

## Summary

The MedGemma Triage System is a comprehensive medical report triage solution built on modern Python async patterns, LangGraph for pipeline orchestration, and Kubernetes for deployment. The codebase is well-organized with clear separation of concerns between clients, models, pipeline nodes, and infrastructure components.

Key architectural decisions include using MedGemma 27B as the primary text analysis engine with 4B reserved for multimodal image analysis, implementing per-test clinical thresholds for meaningful trend detection using evidence-based Reference Change Values from the Westgard biological variation database, generating AI-classified Patient Tapestry body maps in notification emails for instant visual clinical overview, and designing a microservices architecture that separates scheduling, processing, and API concerns.

The system is ready for deployment to the DGX Spark K3s cluster and demonstration for the Kaggle MedGemma Impact Challenge.
