# MedGemma Triage System - Architecture

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DGX SPARK (K3s Cluster)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  SCHEDULER POD  │  │   WORKER POD    │  │    API POD      │             │
│  │                 │  │                 │  │                 │             │
│  │  APScheduler    │  │  LangGraph      │  │  FastAPI        │             │
│  │  - Poll AWS API │  │  Pipeline       │  │  - /health      │             │
│  │  - Backpressure │  │  - 8 steps      │  │  - /process     │             │
│  │  - Queue to     │  │  - Consume from │  │  - /status      │             │
│  │    Redis        │  │    Redis queue  │  │                 │             │
│  │  Replicas: 1    │  │  Replicas: 1    │  │  Replicas: 2    │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                            │
│  ┌─────────────────────────────┴─────────────────────────────┐             │
│  │                    INFRASTRUCTURE PODS                     │             │
│  │                                                            │             │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐             │             │
│  │  │ MongoDB  │  │  Redis   │  │  OpenSearch  │             │             │
│  │  │ :30017   │  │  :30379  │  │    :30920    │             │             │
│  │  └──────────┘  └──────────┘  └──────────────┘             │             │
│  └────────────────────────────────────────────────────────────┘             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                        HOST NETWORK (Model Servers)                         │
│                                                                             │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐          │
│  │     MedGemma 27B IT         │  │     MedGemma 4B IT          │          │
│  │     (TEXT-ONLY)             │  │     (MULTIMODAL)            │          │
│  │                             │  │                             │          │
│  │  Port: 8357                 │  │  Port: 8358                 │          │
│  │  GPU: ~51 GB                │  │  GPU: ~8 GB                 │          │
│  │                             │  │                             │          │
│  │  PRIMARY MODEL:             │  │  RADIOLOGY ONLY:            │          │
│  │  - Classification           │  │  - Image analysis           │          │
│  │  - Lab value extraction     │  │  - X-ray, CT, MRI, PET      │          │
│  │  - Lab/pathology analysis   │  │  - Produces findings for    │          │
│  │  - Radiology synthesis      │  │    27B synthesis            │          │
│  └─────────────────────────────┘  └─────────────────────────────┘          │
│                                                                             │
│  NOTE: Model servers run on host (not in K3s) due to GB10 GPU requirements  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AWS BACKEND SERVICE                               │
│                                                                             │
│  API Gateway + Lambda + DynamoDB + S3                                       │
│  https://<your-api-id>.execute-api.<region>.amazonaws.com/prod               │
│                                                                             │
│  Endpoints:                                                                 │
│  - GET  /reports/pending     → Pending reports to process                   │
│  - GET  /notes/pending       → Pending patient notes                        │
│  - PATCH /reports/update/:id → Mark report as processed                     │
│  - PATCH /notes/update/:id   → Mark note as processed                       │
│  - GET  /patients/:id        → Patient demographics                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Patient Tapestry Visualization

The system includes a Patient Tapestry — a color-coded SVG body map embedded in notification emails that gives clinicians an instant visual overview of a patient's affected body systems before reading any text.

### Tapestry Layout

The tapestry renders three visual areas:

1. **On-Body Organs** (7 regions): Brain, Thyroid, Lungs, Heart, Liver, Pancreas, Kidneys — rendered as ellipses on a human silhouette
2. **Spine Vertebrae** (16 segments): Segmented column to the right of the body, from neck to lower back
3. **Body Systems Grid** (12 circles in 4×3 grid): Blood, Bone, Arteries, Nerves, Immune, Reproductive, Endocrine, GI, Skin, Urinary, Rheumatology, Genomic

### Color Scheme

| Color | Meaning | Hex |
|-------|---------|-----|
| Green | Normal / no issues | #4CAF50 |
| Yellow | Caution / borderline | #FFEB3B |
| Orange | Alert / abnormal | #FF9800 |
| Red | Critical / emergency | #F44336 |

### Special Icons

- **Red X** (✕): Spans the organ/circle at 70% inset — indicates mass, tumor, or cancer
- **Orange Triangle** (▲): Top-left corner — indicates anatomical finding (fracture, hemorrhage, etc.)

### AI-Powered Classification (Primary Path)

When MedGemma 27B is available, the tapestry uses AI classification:

1. `_gather_patient_summary()` compiles ALL patient data from 5 MongoDB sources:
   - Abnormal lab values (flagged only, up to 60)
   - Radiology findings with notes (up to 40)
   - Processed report findings + analysis summaries (up to 40)
   - Patient history (recent reports + notes, up to 10)
   - Clinical notes from processed_notes collection (up to 30)

2. `classify_tapestry_regions()` sends the compiled summary to MedGemma 27B with a detailed prompt describing all 20 body regions, severity levels, and special flags

3. MedGemma returns a JSON array of affected regions with severity, is_mass, is_anatomical, and reason fields

4. The tapestry renderer applies the classifications to all three visual areas (body, spine, grid)

### Keyword Fallback Path

If MedGemma 27B is unavailable or the classification fails, the tapestry falls back to keyword-based classification using:
- `LAB_TO_REGION` dictionary mapping ~120 lab test names to body regions
- `RADIOLOGY_REGION_NORMALISE` dictionary mapping radiology body_region values
- `_TAPESTRY_REGION_KEYWORDS` for free-text region detection
- `_TAPESTRY_MASS_KEYWORDS` and `_TAPESTRY_ANATOMICAL_KEYWORDS` for special icon detection

### Feature Flag

The tapestry is controlled by the `TAPESTRY_ENABLED` environment variable (set in the configmap). When disabled, emails are sent without the body map.

---

## Component Responsibilities

### Scheduler Pod (`report-scheduler`)
- **Replicas:** 1 (singleton to avoid duplicate polling)
- **Function:** Polls AWS API every 60 seconds for pending reports/notes
- **Output:** Queues items to Redis for worker consumption
- **Lock:** Uses Redis distributed lock to prevent duplicate polling
- **Backpressure:** Checks combined queue depth before each poll; skips if at/above threshold (default 20). Self-regulating — resumes automatically when worker drains the queues.

### Worker Pod (`pipeline-worker`)
- **Replicas:** 1 (can scale if model servers support concurrent requests)
- **Function:** Consumes from Redis queue, runs LangGraph pipeline
- **Pipeline Logging:** Every step writes a structured document to OpenSearch via PipelineLogger (fire-and-forget, never blocks pipeline)
- **Pipeline Steps:**
  1. Intake - Download PDF/image from S3
  2. Classify - Determine report type (27B)
  3. Extract - Extract lab values (27B)
  4. Patient Context - Fetch demographics from MongoDB
  5. Historical - Analyze trends from prior results (evidence-based RCV thresholds)
  6. Analyze - AI analysis (27B primary, calls 4B for radiology images)
  7. Score - Calculate priority score
  8. Notify - Send alerts, persist results

**Model Responsibilities:**
- **MedGemma 27B**: Primary model for ALL text analysis - classification, extraction, routing, and final analysis
- **MedGemma 4B**: ONLY used for radiology image analysis (multimodal). Called during Step 6 when radiology images are present.

### API Pod (`triage-api`)
- **Replicas:** 2 (can scale horizontally)
- **Function:** REST API for manual triggers and status queries
- **Endpoints:**
  - `GET /health` - Health check
  - `POST /process/{report_id}` - Manual trigger
  - `GET /status/{report_id}` - Get processing status
  - `GET /queue/stats` - Queue statistics

## Data Flow

```
AWS API                Redis Queue              Worker                MongoDB        OpenSearch
   │                       │                      │                      │               │
   │  GET /reports/pending │                      │                      │               │
   │◄──────────────────────│                      │                      │               │
   │                       │  Backpressure check  │                      │               │
   │                       │  (skip if depth ≥20) │                      │               │
   │  [reports]            │                      │                      │               │
   │──────────────────────►│  LPUSH report_queue  │                      │               │
   │                       │◄─────────────────────│                      │               │
   │                       │                      │                      │               │
   │                       │  RPOP report_queue   │                      │               │
   │                       │─────────────────────►│                      │               │
   │                       │                      │                      │               │
   │                       │                      │  Run Pipeline        │               │
   │                       │                      │─────────────────────►│               │
   │                       │                      │                      │               │
   │                       │                      │  Log each step       │               │
   │                       │                      │─────────────────────────────────────►│
   │                       │                      │                      │               │
   │  PATCH /reports/update│                      │                      │               │
   │◄──────────────────────│──────────────────────│                      │               │
   │                       │                      │                      │               │
```

## Kubernetes Manifests

| File | Description |
|------|-------------|
| `namespace.yaml` | Creates `medgemma-triage` namespace |
| `configmap.yaml` | Non-sensitive configuration |
| `secrets.yaml` | Sensitive credentials (not in git) |
| `mongodb.yaml` | MongoDB StatefulSet + Service |
| `redis.yaml` | Redis Deployment + Service |
| `opensearch.yaml` | OpenSearch + Dashboards |
| `scheduler-deployment.yaml` | APScheduler pod |
| `worker-deployment.yaml` | Pipeline worker pod |
| `api-deployment.yaml` | FastAPI pod + Service |

## Deployment Commands

```bash
# Deploy infrastructure first
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/mongodb.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/opensearch.yaml

# Build and load application image
docker build -t medgemma-triage:latest .
sudo k3s ctr images import medgemma-triage.tar

# Deploy application components
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/scheduler-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml
```

## Why Model Servers Run on Host

MedGemma models run directly on the host (not in K3s) because:

1. **GB10 GPU Support:** Requires PyTorch nightly (cu128) which isn't available in NVIDIA containers
2. **Memory Management:** Direct GPU access allows better memory allocation
3. **vLLM Incompatibility:** MedGemma's MedSigLIP has head_dim=72 which flash attention doesn't support

The K3s pods use `hostNetwork: true` to access model servers at `localhost:8357` and `localhost:8358`.
