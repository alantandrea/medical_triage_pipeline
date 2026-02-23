# AWS Backend Service — Medical Reports & Patient Notes

AWS serverless backend for the MedGemma Impact Challenge. This service provides the cloud-side REST API that the edge-based MedGemma AI pipeline (running on NVIDIA DGX Spark) consumes. It manages patient demographics, generates realistic medical reports (lab, radiology, pathology), receives patient SMS notes via Twilio, and tracks AI processing state.

## Architecture Overview

```
                        AWS Cloud (us-east-1)
 +--------------------------------------------------------+
 |                                                        |
 |   API Gateway (REST)                                   |
 |   |-- /patients          -> ListPatients Lambda        |
 |   |-- /patients/{id}     -> GetPatient Lambda          |
 |   |-- /reports/generate  -> GenerateReport Lambda      |
 |   |-- /reports/{pid}     -> GetReports Lambda          |
 |   |-- /reports/pending   -> GetPendingReports Lambda   |
 |   |-- /reports/update/*  -> UpdateReport Lambda        |
 |   |-- /notes             -> ReceiveNote Lambda (Twilio)|
 |   |-- /notes/pending     -> GetPendingNotes Lambda     |
 |   |-- /notes/update/*    -> UpdateNote Lambda          |
 |   |-- /notes/generate    -> GenerateNote Lambda        |
 |   |-- /seed              -> SeedPatients Lambda        |
 |   +-- /seed/images       -> SeedImages Lambda          |
 |                                                        |
 |   IAM Roles                                            |
 |   +-- medgemma-challenge-presign-role                  |
 |       (Dedicated STS role for pre-signed URL signing)  |
 |                                                        |
 |   DynamoDB                                             |
 |   |-- patient-master     (100 seeded patients)         |
 |   |-- patient-results    (lab/radiology/path reports)  |
 |   +-- patient-notes      (SMS-submitted patient notes) |
 |                                                        |
 |   S3 Buckets                                           |
 |   |-- reports bucket     (generated PDFs + images)     |
 |   +-- medical-images     (240 real images: X-ray,      |
 |                           CT, MRI from public datasets)|
 |                                                        |
 |   Bedrock (Claude Haiku) -- vitals extraction from SMS |
 |                                                        |
 +------------------------+-----------------------------+
                           | HTTPS
                           v
                   DGX Spark (Edge)
             MedGemma 27B + 4B AI Pipeline
```

## Infrastructure at a Glance

| Resource | Details |
|----------|---------|
| **Region** | us-east-1 |
| **IaC** | AWS CDK (TypeScript) |
| **Runtime** | Node.js 18.x Lambda |
| **Database** | DynamoDB (3 tables, 5 GSIs, pay-per-request) |
| **Storage** | 2 S3 buckets (reports + medical images) |
| **API** | API Gateway REST with CORS |
| **AI** | Bedrock Claude Haiku (SMS vitals extraction) |
| **IAM** | 13 roles (12 Lambda + 1 presign role) |

## Prerequisites

- **AWS CLI** configured with credentials (`aws configure`)
- **Node.js 18+**
- **AWS CDK CLI** (`npm install -g aws-cdk`)
- **Python 3.10+** with `boto3`, `datasets`, `Pillow`, `medmnist` (for image seeding scripts)
- An AWS account with permissions for Lambda, DynamoDB, S3, API Gateway, IAM, and Bedrock

## Deployment

```bash
# 1. Install dependencies
npm install

# 2. Build TypeScript
npm run build

# 3. Bootstrap CDK (first time only)
npx cdk bootstrap

# 4. Deploy the stack
npx cdk deploy
```

The deployment outputs the API Gateway URL. Save this -- it's needed by the edge pipeline.

## Post-Deployment Setup

After deployment, initialize the data:

```bash
# Save your API URL (from CDK output)
API_URL="https://<your-api-id>.execute-api.us-east-1.amazonaws.com/prod"

# 1. Seed 100 sample patients with demographics
curl -X POST "$API_URL/seed"

# 2. Seed real medical images from public datasets (X-ray, CT, MRI)
pip install datasets boto3 Pillow medmnist
python scripts/seed_real_images.py

# 3. Generate sample reports (run multiple times for more data)
for i in $(seq 1 50); do
  curl -s -X POST "$API_URL/reports/generate" > /dev/null
done

# 4. Generate sample patient notes
for i in $(seq 1 20); do
  curl -s -X POST "$API_URL/notes/generate" > /dev/null
done
```

## Real Medical Images

The system uses **240 real medical images** from three public datasets, organized by modality and severity:

| Modality | Dataset | License | Images |
|----------|---------|---------|--------|
| X-ray | NIH ChestX-ray14 (BahaaEldin0/NIH-Chest-Xray-14) | CC0 Public Domain | 80 |
| CT | MedMNIST v2 OrganAMNIST (224x224 axial slices) | CC BY 4.0 | 80 |
| MRI | Brain Tumor MRI Dataset (AIOmarRehan) | CC0 Public Domain | 80 |

Each modality has 20 images per severity level (normal, minor, major, critical). The report generator picks a random image matching the report's modality and severity.

**S3 modality mapping** (in the report generator):
- `xray` reports -> `xray/` images
- `ct` reports -> `ct/` images
- `mri` reports -> `mri/` images
- `mra` reports -> `mri/` images (reuses MRI)
- `pet` reports -> `ct/` images (reuses CT)
- `lab` and `path` reports -> no image (text-only PDFs)

**Seeding script:** `scripts/seed_real_images.py` downloads images via streaming from HuggingFace/medmnist and uploads to S3 with metadata (finding, severity, modality, source, license).

## Pre-Signed URL Security (STS Credential Fix)

Pre-signed URLs are generated by the `GET /reports/pending` Lambda. A dedicated IAM role (`medgemma-challenge-presign-role`) is used to sign URLs with **guaranteed fresh STS credentials**.

**Why this matters:** Lambda execution role credentials have an unpredictable remaining lifetime. If the credentials have < 1 hour remaining when URLs are signed, the URLs expire early (403 Forbidden) even if `expiresIn` is set to a longer value. The effective URL lifetime is `min(expiresIn, remaining_STS_credential_lifetime)`.

**Solution:** The Lambda calls `STS.AssumeRole()` on the dedicated presign role with `DurationSeconds: 3600`, guaranteeing the signing credentials have exactly 1 hour of lifetime. The `expiresIn` is also set to 3600 to match.

**Edge batch size recommendation:** With 1-hour URL TTL, the edge should request batches of 15 or fewer reports (15 x 3 min = 45 min, well within the 1-hour window).

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/patients` | List all patients (paginated, default 100) |
| `GET` | `/patients/{id}` | Get specific patient by ID |
| `POST` | `/reports/generate` | Generate report for random patient |
| `POST` | `/reports/generate/{patient_id}` | Generate report for specific patient |
| `GET` | `/reports/{patient_id}` | Get all reports for a patient (with presigned URLs) |
| `GET` | `/reports/pending` | Get unprocessed reports for AI pipeline |
| `PATCH` | `/reports/update/{report_id}` | Mark report as processed with AI results |
| `POST` | `/notes` | Receive patient SMS via Twilio webhook |
| `POST` | `/notes/generate` | Generate sample patient note for testing |
| `POST` | `/notes/generate/{patient_id}` | Generate note for specific patient |
| `GET` | `/notes/pending` | Get unprocessed notes for AI pipeline |
| `PATCH` | `/notes/update/{note_id}` | Mark note as processed with AI results |
| `POST` | `/seed` | Seed 100 sample patients |
| `POST` | `/seed/images` | Seed medical images (legacy Lambda) |

## Report Types

| Type | Description | Image | Source Pool |
|------|-------------|-------|-------------|
| `lab` | Blood panels (BMP, CBC, CMP, Lipid, A1C, Thyroid, PSA, Liver) | No | Quest, LabCorp, ARUP, Mayo, BioReference |
| `xray` | Chest X-ray | Yes (NIH ChestX-ray14) | Regional Medical Imaging, University Hospital, etc. |
| `ct` | CT scan | Yes (MedMNIST OrganAMNIST) | Same radiology pool |
| `mri` | MRI scan | Yes (Brain Tumor MRI) | Same radiology pool |
| `mra` | MR Angiography | Yes (reuses MRI images) | Same radiology pool |
| `pet` | PET scan | Yes (reuses CT images) | Same radiology pool |
| `path` | Pathology/biopsy | No | PathGroup, AmeriPath, Dianon, Aurora |

## Severity Distribution

- **40%** Normal
- **25%** Minor abnormalities
- **20%** Major findings
- **15%** Critical (emergent)

## DynamoDB Tables

### `medgemma-challenge-patient-master`
| Attribute | Type | Description |
|-----------|------|-------------|
| `patient_id` | Number (PK) | Unique patient identifier (1-100) |
| `first_name`, `last_name` | String | Patient name |
| `patient_dob` | String | Date of birth (YYYY-MM-DD) |
| `sex` | String | M or F |
| `cell_phone` | String | Cell phone (GSI: `cell-phone-index`) |
| `home_phone`, `work_phone` | String | Additional phone numbers |
| `address_1`, `city`, `state`, `zipcode` | String | Address fields |

### `medgemma-challenge-patient-results`
| Attribute | Type | Description |
|-----------|------|-------------|
| `patient_id` | Number (PK) | Patient identifier |
| `report_id` | String (SK) | UUID, also GSI: `report_id-index` |
| `report_type` | String | lab, xray, ct, mri, mra, pet, path |
| `severity` | String | normal, minor, major, critical |
| `report_final_ind` | String | "true"/"false" -- GSI: `report_final_ind-index` |
| `report_pdf_s3_key` | String | S3 key for PDF |
| `report_image_s3_key` | String | S3 key for medical image (nullable) |
| `image_source` | Map | Dataset, license, modality metadata |
| `created_at` | String | ISO timestamp |

### `medgemma-challenge-patient-notes`
| Attribute | Type | Description |
|-----------|------|-------------|
| `patient_id` | Number (PK) | Patient identifier |
| `note_id` | String (SK) | UUID, also GSI: `note_id-index` |
| `note_text` | String | Original SMS text |
| `processed` | String | "true"/"false" -- GSI: `processed-index` |
| `temperature`, `pain_scale`, `sp02`, etc. | Number | Extracted vitals |
| `symptoms`, `urgency_indicators` | List | Extracted symptoms |
| `extraction_confidence` | String | high, medium, low |

## S3 Structure

```
medgemma-challenge-reports-{account}/
  reports/{patient_id}/{report_id}.pdf
  images/{patient_id}/{report_id}.png

medgemma-challenge-medical-images-{account}/
  xray/normal/no_finding_001.png ... no_finding_020.png
  xray/minor/atelectasis_001.png ... effusion_005.png
  xray/major/pneumonia_001.png ... mass_008.png
  xray/critical/pneumothorax_001.png ... cardiomegaly_010.png
  ct/normal/bladder_001.png ... femur_right_010.png
  ct/minor/heart_001.png ... kidney_right_010.png
  ct/major/liver_001.png ... lung_right_010.png
  ct/critical/spleen_001.png ... stomach_010.png
  mri/normal/no_tumor_001.png ... no_tumor_020.png
  mri/minor/pituitary_001.png ... pituitary_020.png
  mri/major/meningioma_001.png ... meningioma_020.png
  mri/critical/glioma_001.png ... glioma_020.png
  index.json
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/seed_real_images.py` | Downloads 240 real medical images from public datasets and uploads to S3 |
| `scripts/clear_old_data.py` | Wipes all reports, notes, and S3 objects for a fresh run (preserves patients and images) |

## Security Notes

- **No hardcoded credentials**: All resource names, ARNs, and account IDs are dynamically resolved by CDK at deploy time
- **IAM least-privilege**: Each Lambda receives only the DynamoDB/S3 permissions it needs
- **Dedicated presign role**: Pre-signed URLs are signed with fresh STS credentials from a dedicated role, preventing credential expiry issues
- **Bedrock access**: Only the receive-note Lambda has `bedrock:InvokeModel` permission, scoped to Claude Haiku
- **CORS**: Configured for all origins (development setting)
- **Presigned URLs**: S3 content accessed via time-limited presigned URLs (1 hour for pending reports, 1 hour for direct queries)

## Operations

### Generating More Reports

```bash
# Single report
curl -X POST "$API_URL/reports/generate"

# Report for a specific patient
curl -X POST "$API_URL/reports/generate/42"

# Batch of 50
for i in $(seq 1 50); do curl -s -X POST "$API_URL/reports/generate" > /dev/null; done
```

### Checking Processing Status

```bash
# Count pending vs processed reports
aws dynamodb scan \
  --table-name medgemma-challenge-patient-results \
  --select "SPECIFIC_ATTRIBUTES" \
  --projection-expression "report_type, report_final_ind" \
  --output json | python -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('Items', [])
pending = sum(1 for i in items if i.get('report_final_ind',{}).get('S') == 'false')
done = sum(1 for i in items if i.get('report_final_ind',{}).get('S') == 'true')
print(f'Total: {len(items)}, Pending: {pending}, Processed: {done}')
"
```

### Wiping Data for a Fresh Run

```bash
python scripts/clear_old_data.py
```

This deletes all objects in the reports S3 bucket and all items in the patient-results and patient-notes DynamoDB tables. It preserves the 100 seeded patients and the 240 real medical images.

### Checking Lambda Logs

```bash
# Report generation logs
aws logs filter-log-events \
  --log-group-name "/aws/lambda/medgemma-challenge-generate-report" \
  --start-time $(date -d '1 hour ago' +%s000) \
  --limit 20

# Pending reports Lambda logs
aws logs filter-log-events \
  --log-group-name "/aws/lambda/medgemma-challenge-get-pending-reports" \
  --start-time $(date -d '1 hour ago' +%s000) \
  --limit 20
```

### Redeploying After Code Changes

```bash
npm run build
npx cdk diff      # Preview changes
npx cdk deploy    # Deploy (takes ~1-2 min for Lambda-only changes)
```

## File Structure

```
medical_reports-service/
  bin/                              # CDK app entry point
    medical_reports-service.ts
  lib/                              # CDK stack definition
    medical_reports-service-stack.ts  # All infrastructure as code
  lambda/                           # Lambda function handlers
    patients/
      list/index.js                 # GET /patients
      get/index.js                  # GET /patients/{id}
    reports/
      generate/index.js             # POST /reports/generate (960 lines - PDF generation)
      get/index.js                  # GET /reports/{patient_id}
      pending/index.js              # GET /reports/pending (with STS presign)
      update/index.js               # PATCH /reports/update/{report_id}
    notes/
      receive/index.js              # POST /notes (Twilio webhook + Bedrock)
      pending/index.js              # GET /notes/pending
      update/index.js               # PATCH /notes/update/{note_id}
      generate/index.js             # POST /notes/generate
    seed/index.js                   # POST /seed (100 patients)
    seed-images/index.js            # POST /seed/images (legacy)
  scripts/
    seed_real_images.py             # Download real images from public datasets
    clear_old_data.py               # Wipe reports/notes for fresh run
  docs/
    architecture.md                 # System architecture and data flows
    api-reference.md                # Complete API reference
    data-model.md                   # DynamoDB schemas and S3 structure
    code-walkthrough.md             # Lambda-by-Lambda code walkthrough
  package.json
  tsconfig.json
  cdk.json
```

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `cdk deploy` fails with "bootstrap" error | CDK staging resources not created | Run `npx cdk bootstrap` |
| 403 on pre-signed URL download | STS credentials expired | Fixed by presign role; if still occurring, reduce batch size to 10 |
| `seed_real_images.py` fails with `trust_remote_code` | Old HuggingFace datasets library | `pip install --upgrade datasets` |
| Reports generated but no images | Medical images not seeded | Run `python scripts/seed_real_images.py` |
| Notes Lambda fails with Bedrock error | Bedrock not enabled in region | Enable Claude Haiku in AWS Bedrock console for us-east-1 |
| `generate-report` Lambda timeout | Large PDF + image copy | Normal for first invocation (cold start); subsequent calls are faster |

## Cleanup

```bash
npx cdk destroy
```

This removes all AWS resources (Lambda functions, DynamoDB tables including data, S3 buckets including contents, API Gateway, and IAM roles). This action is irreversible.

## Documentation

See the `docs/` folder for detailed documentation:
- [`docs/architecture.md`](docs/architecture.md) -- System architecture and data flows
- [`docs/api-reference.md`](docs/api-reference.md) -- Complete API reference with request/response schemas
- [`docs/data-model.md`](docs/data-model.md) -- DynamoDB schemas and S3 structure
- [`docs/code-walkthrough.md`](docs/code-walkthrough.md) -- Lambda-by-Lambda code walkthrough

---
*Created for the Google MedGemma Impact Challenge -- Kaggle 2026*
