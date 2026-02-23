# Architecture

## System Overview

The MedGemma Triage System is a two-tier architecture:

1. **AWS Cloud Backend** (this service) -- Manages patient data, generates realistic medical reports, receives patient SMS notes, and serves as the data layer via REST API.
2. **DGX Spark Edge** (see `edge-medical-agent/`) -- Runs the MedGemma 27B (text) and MedGemma 4B (image) models locally on NVIDIA hardware, processing medical content through a LangGraph pipeline.

The edge polls the cloud for unprocessed items, runs AI analysis, then marks items as processed.

## Data Flow: Reports

```
1. Generate Report
   POST /reports/generate
   +-- Lambda picks random patient -> generates report (lab/radiology/path)
       -> creates PDF via PDFKit -> fetches real medical image from S3
       -> uploads PDF + image copy to reports bucket
       -> writes DynamoDB record with report_final_ind="false"

2. Edge Polls for Pending Reports
   GET /reports/pending
   +-- Lambda queries GSI (report_final_ind-index) for report_final_ind="false"
       -> assumes dedicated presign role (STS AssumeRole, 1hr session)
       -> generates presigned S3 URLs using fresh credentials
       -> returns up to 50 reports (oldest first, FIFO)

3. Edge Processes Report
   DGX Spark downloads PDF/image via presigned URLs
   +-- MedGemma 27B analyzes text content (all report types)
   +-- MedGemma 4B analyzes medical images (radiology only)
   +-- LangGraph pipeline: fetch -> extract -> analyze -> classify -> score -> notify

4. Edge Marks Report Processed
   PATCH /reports/update/{report_id}
   +-- Lambda queries GSI (report_id-index) to find composite key
       -> sets report_final_ind="true", stores AI results
       -> report no longer appears in pending queue
```

## Data Flow: Patient Notes

```
1. Patient Sends SMS
   Patient texts their doctor's office number
   +-- Twilio receives SMS -> webhooks POST /notes
       +-- Lambda looks up patient by phone (cell-phone-index GSI)
       +-- Bedrock Claude Haiku extracts structured vitals from free text
           (e.g., "my sugar was 250" -> blood_sugar_level: 250)
       +-- Validates ranges (temp 90-115F, SpO2 50-100%, etc.)
       +-- Stores in DynamoDB with processed="false"
       +-- Returns TwiML confirmation to patient

   OR: Generate test notes via POST /notes/generate

2. Edge Polls for Pending Notes
   GET /notes/pending
   +-- Lambda queries GSI (processed-index) for processed="false"
       -> returns notes with pre-extracted vitals (no presigned URLs needed)

3. Edge Processes Note
   DGX Spark routes note through notes pipeline
   +-- MedGemma 27B analyzes note_text + vitals + symptoms
   +-- Skips image analysis (notes have no images)
   +-- Pipeline: intake -> patient_context -> analyze -> score -> notify

4. Edge Marks Note Processed
   PATCH /notes/update/{note_id}  with JSON body { ai_priority_score, ai_interpretation, alert_level }
   +-- Lambda queries GSI (note_id-index) to find composite key
       -> sets processed="true", stores AI results
       -> note no longer appears in pending queue
```

## Data Flow: Medical Images

```
1. Seed Images (one-time setup)
   python scripts/seed_real_images.py
   +-- Downloads real images from 3 public datasets:
       - NIH ChestX-ray14 (X-ray, CC0)
       - MedMNIST OrganAMNIST (CT, CC BY 4.0)
       - Brain Tumor MRI Dataset (MRI, CC0)
   +-- Uploads 240 images to medical-images bucket
       organized as {modality}/{severity}/{finding}_{index}.png
   +-- Creates index.json manifest

2. Report Generator Copies Images
   When generating a radiology report:
   +-- getMedicalImage() lists images from medical-images bucket
       matching the report's modality and severity
   +-- Picks a random image from the matching pool
   +-- Copies the image to reports bucket at images/{patient_id}/{report_id}.png
   +-- Presigned URLs point to the reports bucket (not medical-images)
```

## Infrastructure Components

### AWS CDK Stack (`lib/medical_reports-service-stack.ts`)

The entire infrastructure is defined as code in a single CDK stack:

| Component | Count | Purpose |
|-----------|-------|---------|
| Lambda Functions | 12 | API handlers (Node.js 18.x) |
| DynamoDB Tables | 3 | Patient master, results, notes |
| Global Secondary Indexes | 5 | Efficient queries without full scans |
| S3 Buckets | 2 | Reports PDFs/images, medical dataset images |
| API Gateway | 1 | REST API with CORS |
| IAM Roles | 13 | 12 Lambda roles + 1 presign role |
| Bedrock Access | 1 | Claude Haiku for note extraction |

### Lambda Functions

| Function | Runtime | Memory | Timeout | Purpose |
|----------|---------|--------|---------|---------|
| list-patients | Node.js 18 | 256 MB | 30s | Paginated patient list |
| get-patient | Node.js 18 | 256 MB | 30s | Single patient lookup |
| generate-report | Node.js 18 | 1024 MB | 120s | PDF generation + S3 upload |
| get-reports | Node.js 18 | 256 MB | 30s | Patient's report history |
| get-pending-reports | Node.js 18 | 256 MB | 30s | Unprocessed report queue |
| update-report | Node.js 18 | 256 MB | 30s | Mark report processed |
| receive-note | Node.js 18 | 512 MB | 30s | Twilio webhook + Bedrock |
| get-pending-notes | Node.js 18 | 256 MB | 30s | Unprocessed note queue |
| update-note | Node.js 18 | 256 MB | 30s | Mark note processed |
| generate-note | Node.js 18 | 256 MB | 30s | Test note generation |
| seed-patients | Node.js 18 | 512 MB | 300s | Seed 100 patients |
| seed-medical-images | Node.js 18 | 1024 MB | 900s | Seed X-ray images (legacy) |

### GSI Design

Five Global Secondary Indexes enable O(1) lookups:

| GSI | Table | Partition Key | Sort Key | Projection | Purpose |
|-----|-------|---------------|----------|------------|---------|
| `report_final_ind-index` | patient-results | report_final_ind | created_at | ALL | Query pending reports |
| `report_id-index` | patient-results | report_id | -- | KEYS_ONLY | Find report by ID for PATCH |
| `cell-phone-index` | patient-master | cell_phone | -- | ALL | Patient lookup by phone |
| `processed-index` | patient-notes | processed | created_at | ALL | Query pending notes |
| `note_id-index` | patient-notes | note_id | -- | KEYS_ONLY | Find note by ID for PATCH |

**Why GSIs for update endpoints?** DynamoDB requires the full composite key (partition + sort) to update an item. The PATCH endpoints receive only the report_id or note_id. Without a GSI, finding the matching patient_id required a full table Scan -- which silently fails to find items once the table exceeds 1 MB (DynamoDB's pagination boundary). The GSI-backed QueryCommand is O(1) regardless of table size.

### Pre-Signed URL Security (Presign Role)

The `medgemma-challenge-presign-role` is a dedicated IAM role used exclusively for signing pre-signed S3 URLs. This solves a critical issue with Lambda credential expiry:

```
Problem:
  Lambda execution role credentials have unpredictable remaining lifetime.
  Pre-signed URL effective TTL = min(expiresIn, remaining_STS_credential_lifetime)
  If credentials have < 1hr remaining, URLs expire early -> 403 Forbidden

Solution:
  GET /reports/pending Lambda calls STS.AssumeRole() on the presign role
  with DurationSeconds=3600, getting guaranteed-fresh 1hr credentials.
  URLs are signed with these fresh credentials -> full 1hr guaranteed.

Role chaining limit:
  Lambda execution role -> presign role is "role chaining"
  AWS caps role chaining at 1hr max session duration
  So expiresIn and DurationSeconds are both set to 3600 (1 hour)
```

The presign role has:
- Trust policy: Only the pending Lambda's execution role can assume it
- Permissions: `s3:GetObject*`, `s3:GetBucket*`, `s3:List*` on the reports bucket
- MaxSessionDuration: 5 hours (allows up to 1hr for role chaining)

## Security Model

- **No hardcoded credentials**: CDK dynamically generates all resource names using `${prefix}-${this.account}` patterns
- **IAM least-privilege**: Each Lambda's execution role grants only the specific DynamoDB/S3 operations it needs (e.g., `grantReadData` vs `grantReadWriteData`)
- **Dedicated presign role**: Prevents pre-signed URL expiry caused by Lambda credential rotation
- **Bedrock access**: Only the receive-note Lambda has `bedrock:InvokeModel` permission, scoped to Claude Haiku
- **Presigned URLs**: S3 objects are never publicly accessible; time-limited presigned URLs are generated per-request
- **CORS**: Currently set to allow all origins for development -- should be restricted for production

## Key Design Decisions

1. **Serverless architecture**: Pay-per-use with zero idle cost. Lambda cold starts are acceptable for this workload.
2. **DynamoDB over RDS**: Schema flexibility for different report types. Pay-per-request billing matches bursty workload.
3. **GSI-backed updates**: Prevents the DynamoDB 1MB Scan pagination bug that caused duplicate AI processing and duplicate email alerts.
4. **Presigned URLs with dedicated signing role**: Edge code doesn't need AWS credentials, and URLs are guaranteed valid for their full TTL.
5. **Bedrock for note extraction**: Claude Haiku handles unstructured patient SMS ("my sugar was five point two") with high accuracy at low cost.
6. **PDFKit for report generation**: Generates authentic-looking lab, radiology, and pathology PDFs that exercise the AI's OCR and interpretation capabilities.
7. **Age-appropriate findings**: Radiology reports use age-gated finding pools -- a 25-year-old won't get atherosclerotic stenosis findings (uses fibromuscular dysplasia instead).
8. **Real medical images from public datasets**: 240 images across 3 modalities (X-ray, CT, MRI) from NIH, MedMNIST, and Brain Tumor datasets. All CC0 or CC BY 4.0 licensed.
9. **Image seeding via Python scripts**: The `scripts/seed_real_images.py` script downloads from HuggingFace/medmnist in streaming mode (no full dataset download) and uploads directly to S3.
