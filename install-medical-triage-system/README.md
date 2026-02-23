# MedGemma Edge Triage System — Installation Guide

A fully automated medical report triage pipeline powered by Google MedGemma (27B + 4B).
The system ingests lab results, radiology images, and pathology reports, then produces
clinician-ready triage assessments with severity scores, trend analysis, and email alerts.

## Architecture

The system uses a **two-tier architecture**:

| Tier | What | Where |
|------|------|-------|
| **Cloud backend** | Patient data, medical reports, pre-signed S3 URLs, image storage | AWS (Lambda, DynamoDB, S3, API Gateway) |
| **Edge pipeline** | AI triage — 8-step LangGraph pipeline with MedGemma inference | Local machine with NVIDIA GPU |

The edge tier runs three application services inside Docker Compose:

```
                     AWS Cloud
          ┌─────────────────────────────┐
          │  API Gateway → Lambda       │
          │  DynamoDB (patients/reports) │
          │  S3 (PDFs + medical images) │
          └──────────────┬──────────────┘
                         │ HTTPS
                         ▼
┌──────────────────────────────────────────────────────────┐
│                   Docker Compose                         │
│                                                          │
│  ┌──────────┐  ┌─────────┐  ┌────────────────────────┐  │
│  │ MongoDB  │  │  Redis  │  │  OpenSearch + Dashboards│  │
│  └──────────┘  └─────────┘  └────────────────────────┘  │
│                                                          │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  API       │  │  Scheduler  │  │  Worker           │  │
│  │  port 8000 │  │  polls AWS  │  │  LangGraph        │  │
│  │  (FastAPI) │  │  every 60s  │  │  8-step pipeline  │  │
│  └────────────┘  └─────────────┘  └──────────────────┘  │
└──────────────────────────┬───────────────────────────────┘
                           │ HTTP (host network)
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌────────────────┐       ┌────────────────┐
     │ MedGemma 27B   │       │ MedGemma 4B    │
     │ (text triage)  │       │ (radiology OCR) │
     │ port 8357      │       │ port 8358       │
     └────────────────┘       └────────────────┘
              Host GPU (NVIDIA)
```

**Application services:**

- **API** (`main.py`) — FastAPI REST server on port 8000. Exposes health checks, query endpoints, and the triage dashboard.
- **Scheduler** (`python -m src.scheduler.report_poller`) — Polls the AWS backend every 60 seconds for new reports and queues them into Redis.
- **Worker** (`python -m src.worker.pipeline_worker`) — Consumes jobs from the Redis queue and runs the 8-step LangGraph triage pipeline using MedGemma.

---

## Step 0: Prerequisites

| Requirement | Details |
|-------------|---------|
| Docker & Docker Compose | v2.20+ recommended |
| NVIDIA GPU | CUDA-capable, minimum 60 GB VRAM (27B only) or 128 GB (27B + 4B) |
| NVIDIA drivers + CUDA | `nvidia-smi` must work on the host |
| Python 3.11+ | For running model servers on the host |
| HuggingFace account | With [HAI-DEF access](https://huggingface.co/google/medgemma-27b-text-it) approved for MedGemma |
| AWS account | For deploying the cloud backend (CDK stack) |

---

## Step 1: Deploy the AWS Backend

The cloud backend provides the data layer — patient demographics, generated medical reports
(lab, radiology, pathology), real medical images from public datasets, and pre-signed S3 URLs.

Follow the full deployment instructions in:

```
../medical_reports-service/README.md
```

After deployment, note the **API Gateway URL** from the CDK output. You will need it in the
next step. It looks like:

```
https://<your-api-id>.execute-api.us-east-1.amazonaws.com/prod
```

---

## Step 2: Configure

```bash
cd install-medical-triage-system/
cp ../edge-medical-agent/.env.example .env
```

Open `.env` and update these settings:

| Variable | What to set | Required |
|----------|-------------|----------|
| `AWS_API_URL` | The API Gateway URL from Step 1 | Yes |
| `AWS_API_KEY` | Your API Gateway key (if configured) | If applicable |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | SMTP server for email alerts | Yes, for alerts |
| `FROM_EMAIL` | Sender address for triage alerts | Yes, for alerts |
| `CLINICAL_NOTIFICATION_EMAIL` | Clinician who receives urgent alerts | Yes, for alerts |
| `TAPESTRY_ENABLED` | Set to `true` to enable Patient Tapestry body-map visualization in email alerts | Optional |

Everything else has sensible defaults. In particular:

- `LOINC_ENABLE_FUZZY=false` — LOINC fuzzy matching is disabled by default. The system works without LOINC data.
- `POLL_INTERVAL_SECONDS=60` — The scheduler checks for new reports every 60 seconds.
- Threshold values (`THRESHOLD_ROUTINE`, `THRESHOLD_FOLLOWUP`, etc.) control triage severity classification.

---

## Step 3: Start Infrastructure + Application

```bash
docker compose up -d
```

This starts six services:

| Service | Purpose | Port |
|---------|---------|------|
| `mongodb` | Triage results, patient context, audit trail | 27017 |
| `redis` | Job queue between scheduler and worker | 6379 |
| `opensearch` | Full-text search and analytics over triage results | 9200 |
| `opensearch-dashboards` | Web UI for exploring OpenSearch data | 5601 |
| `api` | FastAPI REST server | 8000 |
| `scheduler` | Polls AWS for pending reports, queues to Redis | — |
| `worker` | Runs the 8-step LangGraph triage pipeline | — |

Wait for all services to become healthy:

```bash
docker compose ps
```

---

## Step 4: Start Model Servers

The MedGemma model servers run directly on the host (not in Docker) for full GPU access.

```bash
export HF_TOKEN="your-huggingface-token"
bash setup_models.sh
```

On the first run, this downloads the MedGemma model weights from HuggingFace. Expect
**10–20 minutes** depending on your connection speed. Subsequent starts are fast.

If your GPU has less than 128 GB VRAM, use the `--27b-only` flag to skip the 4B model:

```bash
bash setup_models.sh --27b-only
```

The 4B model handles radiology image analysis. Without it, the system still triages all
text-based reports (lab, pathology) using the 27B model.

---

## Step 5: Seed Test Data

With the AWS backend deployed (Step 1), seed patients and generate reports:

```bash
# Set your API URL
API_URL="https://<your-api-id>.execute-api.us-east-1.amazonaws.com/prod"

# Seed 100 sample patients
curl -X POST "$API_URL/seed"

# Seed real medical images from public datasets
cd ../medical_reports-service
pip install datasets boto3 Pillow medmnist
python scripts/seed_real_images.py

# Generate 50 sample reports (lab, radiology, pathology)
for i in $(seq 1 50); do
  curl -s -X POST "$API_URL/reports/generate" > /dev/null
  echo "Generated report $i/50"
done
```

These reports will have `report_final_ind=false` (pending), which the scheduler will
automatically pick up.

---

## Step 6: Verify

Check that all services are running:

```bash
# Application API
curl http://localhost:8000/health

# MedGemma 27B
curl http://localhost:8357/health

# MedGemma 4B (if started)
curl http://localhost:8358/health

# OpenSearch
curl http://localhost:9200/_cluster/health

# Docker services
docker compose ps
```

OpenSearch Dashboards is available at: http://localhost:5601

---

## Step 7: Watch It Work

The pipeline runs automatically once all services are up:

1. The **scheduler** polls the AWS backend every 60 seconds for pending reports.
2. New reports are queued into **Redis**.
3. The **worker** picks up each report and runs the 8-step LangGraph pipeline:
   - Fetch report PDF and medical image (via pre-signed S3 URL)
   - Extract text (OCR via MedGemma 4B for radiology images)
   - Analyze with MedGemma 27B (clinical assessment, severity scoring, trend analysis)
   - Store results in MongoDB and index in OpenSearch
   - Send email alerts for urgent/critical findings

Monitor the pipeline:

```bash
# Watch worker logs (triage processing)
docker compose logs -f worker

# Watch scheduler logs (report polling)
docker compose logs -f scheduler

# Check triage results in MongoDB
docker exec medgemma-mongodb mongosh --eval "db.getSiblingDB('medgemma_triage').triage_results.find().sort({created_at:-1}).limit(5).pretty()"
```

---

## Stopping

```bash
# Stop model servers
bash stop_models.sh

# Stop all Docker services
docker compose down

# Stop and remove all data volumes
docker compose down -v
```

---

## Troubleshooting

### GPU memory errors

MedGemma 27B requires approximately 51 GB of GPU VRAM. If you see CUDA out-of-memory errors:

- Use `--27b-only` to skip the 4B model and free ~8 GB.
- Close other GPU-intensive applications.
- Check current GPU usage: `nvidia-smi`

### Model download failures

- Verify your HuggingFace token: `echo $HF_TOKEN`
- Confirm you have accepted the [HAI-DEF terms](https://huggingface.co/google/medgemma-27b-text-it) on HuggingFace.
- Check network connectivity to `huggingface.co`.
- If a download was interrupted, re-run `setup_models.sh` — it will resume.

### Port conflicts

| Port | Service | Fix |
|------|---------|-----|
| 8000 | API | Check for other web servers |
| 8357 | MedGemma 27B | Check for existing model servers |
| 8358 | MedGemma 4B | Check for existing model servers |
| 27017 | MongoDB | Stop local MongoDB: `sudo systemctl stop mongod` |
| 6379 | Redis | Stop local Redis: `sudo systemctl stop redis` |
| 9200 | OpenSearch | Stop local OpenSearch/Elasticsearch |

### No reports being processed

1. Confirm the AWS backend has pending reports:
   ```bash
   curl "$API_URL/reports/pending"
   ```
2. Check that `AWS_API_URL` in `.env` is correct.
3. Verify the scheduler is running: `docker compose logs scheduler`
4. Verify Redis has queued jobs: `docker exec medgemma-redis redis-cli LLEN report_queue`

### Model servers not responding

Check the model server logs:

```bash
tail -f ~/medgemma-servers/medgemma_27b.log
tail -f ~/medgemma-servers/medgemma_4b.log
```

If a model server crashed, restart it:

```bash
bash stop_models.sh
export HF_TOKEN="your-huggingface-token"
bash setup_models.sh --skip-install
```

---

*Created for the Google MedGemma Impact Challenge — Kaggle 2026*
