# MedGemma Triage System

An intelligent medical report triage system powered by LangGraph and MedGemma models.

## Overview

This system processes medical reports (labs, pathology, radiology) and patient notes through an 8-step LangGraph pipeline that orchestrates AI-powered analysis using MedGemma 27B and 4B models.

## Architecture

- **APScheduler Service**: Polls for pending reports and invokes the pipeline
- **Report Puller API**: Fetches reports from AWS backend
- **LangGraph Pipeline**: 8-step intelligent analysis workflow
- **Reporting Service**: Email notifications for critical findings
- **LOINC Classification Service**: Standardized lab test normalization via Redis

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# Run patient sync (one-time or daily)
python -m src.jobs.patient_sync --mode full

# Run LOINC ETL (one-time setup)
python -m src.loinc.etl_job --mode full --csv-path ../docs/Loinc_2.81/LoincTable/Loinc.csv

# Start the service
python main.py
```

## API Endpoints

### Health
- `GET /health` - Basic health check
- `GET /health/detailed` - Detailed dependency health

### Patient Sync
- `POST /jobs/patient-sync/full` - Full patient sync from AWS
- `POST /jobs/patient-sync/incremental` - Incremental sync
- `GET /jobs/patient-sync/status` - Sync status

### LOINC Lookup
- `GET /loinc/lookup/code/{loinc_num}` - Lookup by LOINC code
- `GET /loinc/lookup/name/{test_name}` - Lookup by test name
- `GET /loinc/search?query=glucose` - Search LOINC codes
- `GET /loinc/metadata` - LOINC data metadata

### Patients
- `GET /patients/{patient_id}` - Get patient from local MongoDB
- `GET /patients/{patient_id}/lab-history` - Get lab value history

## Directory Structure

```
medical-agent/
├── main.py                     # FastAPI entry point
├── requirements.txt
├── pytest.ini                  # Pytest configuration
├── run_tests.py                # Test runner script
├── .env.example
├── src/
│   ├── config.py               # Pydantic settings
│   ├── clients/                # External service clients
│   │   ├── aws_api.py          # AWS API client
│   │   ├── mongodb_client.py   # MongoDB async client
│   │   ├── redis_client.py     # Redis client
│   │   ├── medgemma_27b.py     # MedGemma 27B client
│   │   ├── medgemma_4b.py      # MedGemma 4B client
│   │   └── loinc_client.py     # LOINC lookup client
│   ├── models/                 # Pydantic data models
│   │   ├── schemas.py          # Core schemas
│   │   └── loinc.py            # LOINC models
│   ├── loinc/                  # LOINC classification service
│   │   ├── loader.py           # CSV to Redis loader
│   │   ├── admin.py            # Admin utilities
│   │   └── etl_job.py          # CLI ETL script
│   ├── jobs/                   # Batch jobs
│   │   └── patient_sync.py     # AWS to MongoDB sync
│   ├── pipeline/               # LangGraph pipeline
│   │   ├── graph.py            # Pipeline definition
│   │   ├── state.py            # Pipeline state
│   │   └── nodes/              # 8 pipeline step nodes
│   └── reporting/              # Notification service
│       └── service.py          # Email notifications
├── tests/                      # Test suite
│   ├── conftest.py             # Pytest fixtures
│   ├── test_models.py          # Model tests
│   ├── test_clients.py         # Client tests
│   ├── test_pipeline.py        # Pipeline tests
│   ├── test_jobs.py            # Job tests
│   ├── test_loinc.py           # LOINC tests
│   └── test_api.py             # API tests
└── data/
    └── loinc/
        └── synonyms.json       # Custom synonym mappings
```

## Testing

Run the test suite:

```bash
# Run all tests
python run_tests.py

# Run with verbose output
python run_tests.py -v

# Run unit tests only
python run_tests.py --unit

# Run integration tests
python run_tests.py --integration

# Run property-based tests
python run_tests.py --property

# Run with coverage report
python run_tests.py --coverage

# Run with HTML coverage report
python run_tests.py --coverage --html

# Run specific tests by keyword
python run_tests.py -k "test_score"
python run_tests.py -k "test_loinc"

# CI mode (more examples for property tests)
python run_tests.py --property --ci

# Or use pytest directly
pytest tests/ -v
pytest tests/test_models.py -v
pytest --cov=src --cov-report=term-missing
```

### Test Categories

| Category | File | Description |
|----------|------|-------------|
| Models | `test_models.py` | Pydantic model validation |
| Clients | `test_clients.py` | Client parsing and helpers |
| Pipeline | `test_pipeline.py` | Pipeline nodes and scoring |
| Jobs | `test_jobs.py` | Patient sync job |
| LOINC | `test_loinc.py` | LOINC loader and admin |
| API | `test_api.py` | FastAPI endpoint structure |
| Reporting | `test_reporting.py` | Notification service |
| Integration | `test_integration.py` | End-to-end scenarios |
| Scoring Properties | `test_scoring_properties.py` | Property-based scoring tests |
| LOINC Properties | `test_loinc_properties.py` | Property-based LOINC tests |

## Deployment

Target: DGX Spark (local deployment)

| Service | Port | Description |
|---------|------|-------------|
| MedGemma 27B | 8357 | Multimodal analysis |
| MedGemma 4B | 8358 | Fast text extraction |
| Redis | 6379 | State & LOINC data |
| MongoDB | 27017 | Patient & lab storage |

## Environment Variables

See `.env.example` for all configurable options. Key settings:

- `TENANT_ID` - Multi-tenant identifier
- `AWS_API_URL` - Backend API endpoint
- `MEDGEMMA_27B_URL` - 27B model endpoint
- `MEDGEMMA_4B_URL` - 4B model endpoint
- `REDIS_URL` - Redis connection
- `MONGODB_URI` - MongoDB connection
