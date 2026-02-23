# MedGemma Triage System

Autonomous medical report triage powered by Google MedGemma, running entirely on edge hardware.

This system continuously monitors incoming lab results, radiology images, and pathology reports, triages them by clinical urgency using MedGemma AI models, and delivers prioritized alerts to physicians — all without sending patient data to the cloud.

Built for the [Google MedGemma Impact Challenge — Kaggle 2026](https://www.kaggle.com/competitions/medgemma-impact-challenge).

Source code: [github.com/alantandrea/medical_triage_pipeline](https://github.com/alantandrea/medical_triage_pipeline)

---

## Architecture

The system uses a two-tier architecture: an AWS serverless backend manages patient data and medical reports, while the edge tier runs the full AI inference pipeline locally on an NVIDIA DGX Spark.

```
                        AWS Cloud
          ┌──────────────────────────────────┐
          │  API Gateway → Lambda            │
          │  DynamoDB (patients, reports)     │
          │  S3 (PDFs, medical images)       │
          │  Bedrock Claude Haiku (SMS notes) │
          └───────────────┬──────────────────┘
                          │ HTTPS
                          ▼
          ┌──────────────────────────────────┐
          │     NVIDIA DGX Spark (Edge)      │
          │                                  │
          │  ┌────────────────────────────┐  │
          │  │  K3s Kubernetes Cluster    │  │
          │  │  ┌──────┐ ┌──────┐ ┌────┐ │  │
          │  │  │Sched.│ │Worker│ │API │ │  │
          │  │  └──────┘ └──────┘ └────┘ │  │
          │  │  MongoDB  Redis  OpenSearch│  │
          │  └────────────────────────────┘  │
          │                                  │
          │  MedGemma 27B (text, port 8357)  │
          │  MedGemma 4B (vision, port 8358) │
          │         128 GB GPU memory        │
          └──────────────────────────────────┘
```

Patient data never leaves the clinic network for inference. The AWS backend provides the data layer only — demographics, generated reports, real medical images from public datasets, and pre-signed S3 URLs. All AI reasoning happens on-device.

---

## What the Edge Pipeline Does

The edge tier is the core of the system. It runs an 8-step LangGraph state machine that processes every incoming report:

| Step | Name | What Happens |
|------|------|-------------|
| 1 | Intake | Downloads the PDF or image from S3 via pre-signed URL |
| 2 | Classify | MedGemma 27B determines report type (lab, pathology, X-ray, CT, MRI, PET) |
| 3 | Extract | MedGemma 27B extracts structured lab values and maps them to LOINC codes |
| 4 | Patient Context | Fetches patient demographics and medical history from MongoDB |
| 5 | Historical | Analyzes trends using vector analysis (velocity + acceleration) and biological variation thresholds (Westgard RCV) |
| 6 | Analyze | MedGemma 27B performs clinical analysis; for radiology, 4B analyzes the image first, then 27B synthesizes |
| 7 | Score | Calculates a composite priority score (0–100) from multiple clinical factors |
| 8 | Notify | Sends prioritized email alerts with AI summary, patient history, and Patient Tapestry body map |

### Key Features

- **Dual MedGemma models** — 27B for all text reasoning, 4B for radiology image analysis, orchestrated automatically by report type
- **LOINC normalization** — Lab values mapped to standard codes via exact synonym lookup + fuzzy matching against LOINC 2.81
- **Biological variation thresholds** — Reference Change Values (RCV) from Westgard data at 95% confidence, replacing arbitrary percentage thresholds
- **Vector analysis** — First and second derivatives (velocity and acceleration) of lab trends to detect deteriorating trajectories
- **Composite scoring** — AI urgency + critical trends + RCV-significant changes + critical flags + report type modifiers + radiology growth tracking
- **Patient Tapestry** — Color-coded SVG body map showing affected systems at a glance, classified by MedGemma 27B with keyword fallback
- **Backpressure and dedup** — Redis queue monitoring with configurable threshold, SHA-256 deduplication, distributed locks
- **Full audit trail** — Every pipeline step logged to OpenSearch with per-step timing

---

## What the AWS Backend Does

The cloud tier provides the data layer that feeds the edge pipeline:

- **Patient demographics** — 100 seeded patients with full profiles stored in DynamoDB
- **Medical report generation** — Realistic lab panels, radiology reports, and pathology findings with appropriate severity distributions (40% normal, 25% minor, 20% major, 15% critical)
- **Real medical images** — 240 images from three public datasets: NIH ChestX-ray14 (X-ray), MedMNIST OrganAMNIST (CT), and Brain Tumor MRI Dataset (MRI), all CC0/CC BY 4.0 licensed
- **Patient SMS notes** — Twilio webhook receives patient messages; Amazon Bedrock Claude Haiku extracts vitals and symptoms
- **Pre-signed S3 URLs** — Secure, time-limited access to PDFs and images using a dedicated STS presign role

Infrastructure is defined entirely in AWS CDK (TypeScript) and deploys with a single `npx cdk deploy` command.

<!-- 
============================================================
PLACEHOLDER: AWS BACKEND — CLAUDE'S NOTES
============================================================
Claude — this section is reserved for you to add any additional 
notes, observations, or details about the AWS backend service 
(medical_reports-service/) that you think would be helpful for 
the Kaggle judges. Topics you might cover:

- Design decisions you made for the Lambda architecture
- How the report generation logic works (severity distribution, 
  PDF generation, image assignment)
- The STS credential fix for pre-signed URLs
- DynamoDB table design and GSI strategy
- The Bedrock integration for patient SMS notes
- Anything else you want to highlight

Feel free to replace this entire comment block with your content.
============================================================
-->

---

## Repository Contents

```
KaggleExport/
├── README.md                          ← You are here
├── MedGemma_Technical_Writeup.docx    ← Competition writeup document
├── edge-medical-agent/                ← Edge AI triage pipeline (Python)
│   ├── Edge_Medical_Triage_System.md  ← Detailed technical documentation
│   ├── README.md                      ← Code-level README with API docs
│   ├── src/                           ← Pipeline source code
│   ├── tests/                         ← Test suite with property-based tests
│   ├── k8s/                           ← Kubernetes manifests for K3s
│   └── docs/                          ← Architecture, deployment, walkthrough
├── medical_reports-service/           ← AWS serverless backend (CDK + Lambda)
│   ├── README.md                      ← Full backend documentation
│   ├── lib/                           ← CDK stack definition
│   ├── lambda/                        ← Lambda function handlers
│   └── scripts/                       ← Data seeding and cleanup scripts
├── install-medical-triage-system/     ← Standalone installation guide
│   ├── README.md                      ← Step-by-step setup instructions
│   ├── docker-compose.yml             ← Docker Compose for all services
│   ├── setup_models.sh                ← MedGemma model server launcher
│   └── stop_models.sh                 ← Model server shutdown
└── video/                             ← Demo video
```

---

## Getting Started

For a complete step-by-step installation guide (AWS backend deployment, Docker Compose setup, model server configuration, and end-to-end verification), see:

**[install-medical-triage-system/README.md](install-medical-triage-system/README.md)**

For detailed technical documentation on the edge pipeline, see:

**[edge-medical-agent/Edge_Medical_Triage_System.md](edge-medical-agent/Edge_Medical_Triage_System.md)**

For the AWS backend service documentation, see:

**[medical_reports-service/README.md](medical_reports-service/README.md)**

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| AI Models | Google MedGemma 27B IT, MedGemma 4B IT |
| Pipeline | LangGraph (state machine), Python, FastAPI |
| Edge Platform | NVIDIA DGX Spark (GB10, 128 GB GPU), K3s |
| Data Stores | MongoDB, Redis, OpenSearch |
| Cloud Backend | AWS CDK, Lambda, DynamoDB, S3, API Gateway |
| Patient Notes | Twilio SMS, Amazon Bedrock Claude Haiku |
| Lab Standards | LOINC 2.81, Westgard biological variation data |
| Notifications | SMTP email with HTML + inline SVG tapestry |

---

## Testing Results

133 medical reports and 64 patient notes processed end-to-end with zero pipeline errors. All urgent and important findings triggered email notifications with patient history context and Patient Tapestry visualizations. Full audit trail captured in OpenSearch (1,981+ log entries).

---

*MedGemma Impact Challenge — Kaggle 2026*
