# Edge Medical Triage System

An autonomous AI pipeline that continuously monitors incoming medical data — lab results, radiology reports, pathology findings, and patient notes — and triages them by clinical urgency using Google's MedGemma models, all running locally on a single NVIDIA DGX Spark.

---

## The Problem

Physicians in busy practices face an overwhelming volume of incoming results every day. Lab panels, radiology reads, pathology reports, and patient messages all land in the same undifferentiated inbox. There is no automated prioritization — a routine lipid panel sits next to a critically low hemoglobin. A steadily rising creatinine over three visits may go unnoticed until it crosses a critical threshold. A tension pneumothorax finding on a CT scan waits in the queue until the doctor gets to it.

This system closes that gap by autonomously triaging every result the moment it arrives, scoring it by clinical urgency, and alerting the physician with a rich context package — AI summary, trend analysis, patient history, and a visual body map — so the most critical findings get attention first.

---

## How It Works

The system is a two-tier architecture: an AWS serverless backend manages patient data and serves it via API, while the DGX Spark edge node runs the entire AI inference pipeline locally. Patient data never leaves the clinic network for inference.

### Data Ingestion

An APScheduler service polls the AWS backend every 60 seconds for new medical reports and patient notes. Reports are queued to Redis for processing. A backpressure mechanism monitors queue depth and pauses polling when the pipeline is saturated (default threshold: 20 items), resuming automatically once the worker catches up.

### The 8-Step LangGraph Pipeline

Each report flows through an intelligent state machine built on LangGraph:

| Step | Name | What It Does |
|------|------|-------------|
| 1 | **Intake** | Downloads the PDF or image from S3 via pre-signed URL |
| 2 | **Classify** | MedGemma 27B determines the report type (lab, pathology, X-ray, CT, MRI, PET) |
| 3 | **Extract** | MedGemma 27B extracts structured lab values and maps them to standard LOINC codes |
| 4 | **Patient Context** | Fetches patient demographics and medical history from MongoDB |
| 5 | **Historical** | Analyzes trends across prior results using evidence-based biological variation thresholds |
| 6 | **Analyze** | MedGemma 27B performs clinical analysis; for radiology, MedGemma 4B analyzes the image first, then 27B synthesizes the findings |
| 7 | **Score** | Calculates a composite priority score (0–100) from multiple clinical factors |
| 8 | **Notify** | Sends prioritized email alerts with AI summary, score breakdown, patient history, and Patient Tapestry body map |

Patient-submitted SMS notes (received via Twilio, vitals extracted by Amazon Bedrock Claude Haiku) follow a streamlined 5-step variant that skips PDF download and image analysis.

Every pipeline step is logged to OpenSearch for full auditability.

---

## The AI Models

| Model | Role | GPU Memory |
|-------|------|-----------|
| **MedGemma 27B IT** | Primary model for all text analysis — classification, extraction, clinical reasoning, scoring, and tapestry region classification | ~51 GB |
| **MedGemma 4B IT** | Radiology image analysis only — interprets X-rays, CT, MRI, and PET scans, producing structured findings that 27B then synthesizes | ~8 GB |

Both models run directly on the DGX Spark host (not in containers) using PyTorch with bfloat16 precision. The 27B model handles every text-based decision in the pipeline. The 4B model is called only when radiology images are present, creating a two-stage analysis flow: 27B evaluates → 4B analyzes the image → 27B synthesizes the final clinical summary.

---

## Key Technical Features

### LOINC Normalization

Every extracted lab value is mapped to a standard LOINC code using a two-stage pipeline: exact lookup against a curated synonym table (covering common abbreviations like BMP, CBC, A1C), then fuzzy matching against the LOINC 2.81 database. This ensures that "glucose," "blood sugar," and "GLU" all resolve to the same code, enabling consistent cross-source trend tracking.

### Biological Variation Thresholds (RCV)

Rather than arbitrary percentage thresholds, the system computes Reference Change Values from published Westgard biological variation data. The RCV formula — `RCV = √2 × Z × √(CVA² + CVI²)` — accounts for both analytical imprecision and within-subject biological variation to determine the minimum change between two consecutive results that is statistically significant at 95% confidence. For example, creatinine has an RCV of approximately 18.6%, meaning a change below that threshold is likely normal fluctuation, not a true clinical change.

### Composite Priority Scoring

The scoring engine combines multiple clinical signals into a single 0–100 score:

| Factor | Bonus | Cap |
|--------|-------|-----|
| Base AI urgency score | 0–100 | — |
| Critical trends | +20 each | +40 |
| Significant changes (RCV) | +10 each | +30 |
| Statistical significance | +5 each | +15 |
| Critical lab values | +15 each | +45 |
| Report type (pathology +10, advanced imaging +5) | varies | — |
| Radiology growth patterns | up to +25 for rapid doubling | +40 |

The final score maps to priority levels:

- **Routine** (0–29): No immediate action needed
- **Follow-up** (30–49): Review at next opportunity
- **Important** (50–74): Review today — email alert sent
- **Urgent** (75–100): Immediate attention — urgent email alert sent

### Patient Tapestry

Each email alert includes a Patient Tapestry — a color-coded SVG body map that gives clinicians an instant visual overview of all affected body systems. The tapestry renders a human silhouette with 7 on-body organ regions, a 16-segment spine column, and a 4×3 grid of 12 systemic circles (blood, bone, arteries, nerves, immune, reproductive, endocrine, GI, skin, urinary, rheumatology, genomic).

Regions are colored by severity: green (normal), yellow (caution), orange (alert), red (critical). Special icons mark masses/tumors (red X) and anatomical findings like fractures (orange triangle).

The primary classification path uses MedGemma 27B — the system gathers the patient's complete record from MongoDB (labs, radiology, reports, notes) and prompts the model to classify each affected region. A keyword-based fallback activates automatically if the model is unavailable.


### Backpressure and Deduplication

The scheduler checks combined Redis queue depth before each poll cycle. If the depth meets or exceeds the configurable threshold (default: 20), it skips that cycle and resumes automatically once the worker drains the queues. Before processing any report, the worker checks MongoDB for an existing result with the same report ID — if found, the item is skipped. Combined with a Redis distributed lock on the scheduler, this provides two layers of protection against duplicate processing.

---

## Edge Deployment

The entire system runs on a single NVIDIA DGX Spark (GB10 SoC, 128 GB unified GPU memory, ARM64). Kubernetes is provided by K3s — a lightweight, certified distribution ideal for edge deployments.

### What Runs Where

| Component | Where | Notes |
|-----------|-------|-------|
| Scheduler Pod | K3s | 1 replica, polls AWS every 60s |
| Worker Pod | K3s | 1 replica, runs the 8-step pipeline |
| API Pod | K3s | 2 replicas, FastAPI health/status endpoints |
| MongoDB | K3s | Patient data, lab history, results |
| Redis | K3s | Message queues, distributed locks, LOINC cache |
| OpenSearch | K3s | Pipeline audit logs with dashboards |
| MedGemma 27B | Host | Port 8357, ~51 GB GPU |
| MedGemma 4B | Host | Port 8358, ~8 GB GPU |

The model servers run on the host (not in K3s) because the GB10's Blackwell GPU requires PyTorch nightly with CUDA 12.8 support, which is not yet available in NVIDIA's container images. Application pods use `hostNetwork: true` to access both the model servers on localhost and K3s infrastructure services via ClusterIP DNS.

### Why Edge?

- No patient data leaves the clinic network — all AI inference happens locally
- Zero cloud dependency for inference (only the AWS data layer requires network access)
- A single DGX Spark device runs the entire stack: two MedGemma models, three application services, and three infrastructure services
- Standard Kubernetes tooling (kubectl, Helm) for deployment and monitoring

---

## Report Types Supported

| Type | Description | Has Image? | Model Flow |
|------|-------------|------------|------------|
| Lab | Blood tests (BMP, CBC, A1C, lipid panels, etc.) | No | 27B only |
| Pathology | Biopsies and tissue analysis | No | 27B only |
| X-ray | Chest X-rays | Yes | 27B → 4B → 27B |
| CT | CT scans | Yes | 27B → 4B → 27B |
| MRI | MRI scans | Yes | 27B → 4B → 27B |
| MRA | MR Angiography | Yes | 27B → 4B → 27B |
| PET | PET scans | Yes | 27B → 4B → 27B |
| Patient Note | SMS notes with vitals | No | 27B (5-step variant) |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| AI Models | Google MedGemma 27B IT, MedGemma 4B IT |
| Pipeline Orchestration | LangGraph (state machine) |
| Application Framework | Python, FastAPI, APScheduler |
| Container Orchestration | K3s (lightweight Kubernetes) |
| Message Queue | Redis (FIFO queues + distributed locks) |
| Patient Data Store | MongoDB |
| Audit Logging | OpenSearch + Dashboards |
| Lab Standardization | LOINC 2.81 with fuzzy matching |
| Biological Variation | Westgard RCV database (20+ analytes) |
| Cloud Backend | AWS API Gateway + Lambda + DynamoDB + S3 |
| Patient Notes | Twilio SMS + Amazon Bedrock Claude Haiku |
| Notifications | SMTP email with HTML + inline SVG tapestry |

---

*MedGemma Impact Challenge — Kaggle 2026*
