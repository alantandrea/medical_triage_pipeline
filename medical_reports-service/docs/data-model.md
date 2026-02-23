# Data Model

## DynamoDB Tables

All tables use on-demand (PAY_PER_REQUEST) billing and are created by CDK with the `medgemma-challenge-` prefix.

---

### Table: `medgemma-challenge-patient-master`

Stores patient demographics. Seeded with 100 sample patients via `POST /seed`.

**Keys:**
- Partition Key: `patient_id` (Number)

**Attributes:**

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `patient_id` | Number | Unique identifier (1-100) | `42` |
| `first_name` | String | First name | `"James"` |
| `last_name` | String | Last name | `"Smith"` |
| `patient_dob` | String | Date of birth (YYYY-MM-DD) | `"1965-03-15"` |
| `sex` | String | Biological sex | `"M"` or `"F"` |
| `cell_phone` | String | Cell phone number | `"555-123-4567"` |
| `home_phone` | String | Home phone | `"555-234-5678"` |
| `work_phone` | String | Work phone (may be empty) | `"555-345-6789"` |
| `address_1` | String | Street address | `"123 Main St"` |
| `address_2` | String | Apartment/suite (may be empty) | `"Apt 301"` |
| `city` | String | City | `"New York"` |
| `state` | String | State abbreviation | `"NY"` |
| `zipcode` | String | ZIP code | `"10001"` |

**GSIs:**

| Index Name | Partition Key | Sort Key | Projection | Purpose |
|------------|---------------|----------|------------|---------|
| `cell-phone-index` | `cell_phone` (String) | — | ALL | Lookup patient by phone (Twilio SMS) |

---

### Table: `medgemma-challenge-patient-results`

Stores medical reports (lab, radiology, pathology). Generated via `POST /reports/generate`.

**Keys:**
- Partition Key: `patient_id` (Number)
- Sort Key: `report_id` (String, UUID)

**Attributes:**

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `patient_id` | Number | Patient identifier | `42` |
| `report_id` | String | UUID report identifier | `"a1b2c3d4-..."` |
| `report_date` | String | Report date (YYYY-MM-DD) | `"2026-02-19"` |
| `report_type` | String | Report category | `"lab"`, `"xray"`, `"ct"`, `"mri"`, `"mra"`, `"pet"`, `"path"` |
| `reporting_source` | String | Lab/facility name | `"Quest Diagnostics"` |
| `severity` | String | Severity level | `"normal"`, `"minor"`, `"major"`, `"critical"` |
| `report_pdf_s3_key` | String | S3 key for PDF | `"reports/42/a1b2c3d4.pdf"` |
| `report_image_s3_key` | String or null | S3 key for medical image | `"images/42/a1b2c3d4.png"` |
| `report_final_ind` | String | Processing status | `"false"` (pending) or `"true"` (processed) |
| `created_at` | String | ISO timestamp | `"2026-02-19T10:30:00.000Z"` |
| `image_source` | Map or null | Medical image provenance | `{ "dataset": "medical_dataset", "license": "CC0/CC-BY" }` |
| `processed_at` | String | When AI processed (set by PATCH) | `"2026-02-19T15:30:00.000Z"` |
| `ai_summary` | String | AI-generated summary (set by PATCH) | `"Normal chest X-ray..."` |
| `ai_severity` | String | AI-assessed severity (set by PATCH) | `"normal"` |
| `ai_urgency_score` | Number | AI urgency score 0-1 (set by PATCH) | `0.15` |
| `ai_priority_level` | String | AI priority (set by PATCH) | `"routine"`, `"urgent"`, `"emergent"` |

**GSIs:**

| Index Name | Partition Key | Sort Key | Projection | Purpose |
|------------|---------------|----------|------------|---------|
| `report_final_ind-index` | `report_final_ind` (String) | `created_at` (String) | ALL | Query pending/processed reports |
| `report_id-index` | `report_id` (String) | — | KEYS_ONLY | Lookup by report_id for PATCH |

**GSI Design Note:** `report_id-index` uses KEYS_ONLY projection (returns only `patient_id` + `report_id`) because we only need the composite key to perform the UpdateCommand. This minimizes GSI storage and write costs.

---

### Table: `medgemma-challenge-patient-notes`

Stores patient-submitted notes (via SMS or generated for testing).

**Keys:**
- Partition Key: `patient_id` (Number)
- Sort Key: `note_id` (String, UUID)

**Attributes:**

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `patient_id` | Number | Patient identifier | `42` |
| `note_id` | String | UUID note identifier | `"b2c3d4e5-..."` |
| `note_date` | String | When note was received | `"2026-02-19T10:30:00.000Z"` |
| `created_at` | String | Creation timestamp | `"2026-02-19T10:30:00.000Z"` |
| `from_phone` | String | Source phone number | `"+15551234567"` |
| `patient_name` | String | Patient's full name | `"James Smith"` |
| `processed` | String | Processing status | `"false"` (pending) or `"true"` (processed) |
| `note_text` | String | Original SMS text | `"My sugar was 250..."` |
| **Extracted Vitals** | | | |
| `temperature` | Number or null | Body temp (Fahrenheit) | `101.2` |
| `pain_scale` | Number or null | Pain level (0-10) | `6` |
| `sp02` | Number or null | Oxygen saturation (%) | `94` |
| `systolic` | Number or null | Systolic BP (mmHg) | `145` |
| `diastolic` | Number or null | Diastolic BP (mmHg) | `92` |
| `weight` | Number or null | Weight (lbs) | `175.5` |
| `blood_sugar_level` | Number or null | Blood glucose (mg/dL) | `250` |
| `heart_rate` | Number or null | Heart rate (bpm) | `88` |
| `hemoglobin_a1c` | Number or null | HbA1c (%) | `7.2` |
| **Symptoms & Urgency** | | | |
| `symptoms` | List\<String\> | Extracted symptoms | `["dizziness", "nausea"]` |
| `urgency_indicators` | List\<String\> | Urgent findings | `["very high blood sugar"]` |
| `has_urgency` | Boolean | Quick urgency flag | `true` |
| **Metadata** | | | |
| `extraction_method` | String | How vitals were extracted | `"bedrock-haiku"` or `"template-generated"` |
| `extraction_confidence` | String | Confidence level | `"high"`, `"medium"`, `"low"` |
| `values_extracted` | Number | Count of non-null vitals | `3` |
| `severity` | String | Template severity (test notes only) | `"major"` |
| **AI Results (set by PATCH)** | | | |
| `processed_at` | String | When AI processed | `"2026-02-19T15:30:00.000Z"` |
| `ai_priority_score` | Number | AI priority score | `0.85` |
| `ai_interpretation` | String | AI analysis text | `"Patient reports..."` |
| `alert_level` | String | Alert classification | `"high"`, `"medium"`, `"low"` |
| `alert_sent` | Boolean | Whether alert was sent | `true` |

**GSIs:**

| Index Name | Partition Key | Sort Key | Projection | Purpose |
|------------|---------------|----------|------------|---------|
| `processed-index` | `processed` (String) | `created_at` (String) | ALL | Query pending/processed notes |
| `note_id-index` | `note_id` (String) | — | KEYS_ONLY | Lookup by note_id for PATCH |

**Reserved keyword note:** `processed` is a DynamoDB reserved keyword. All queries use `ExpressionAttributeNames` (`#p` → `processed`) to avoid conflicts.

---

## S3 Bucket Structure

### Reports Bucket: `medgemma-challenge-reports-{account}`

```
reports/
  {patient_id}/
    {report_id}.pdf          # Generated PDF (lab, radiology, or pathology)

images/
  {patient_id}/
    {report_id}.png          # Associated medical image (radiology only)
```

- PDFs are generated by PDFKit in the generate-report Lambda
- Images come from the medical-images bucket (copied during report generation)
- Accessed via presigned URLs (1hr for direct queries, 4hr for pending queue)

### Medical Images Bucket: `medgemma-challenge-medical-images-{account}`

```
xray/
  normal/
    normal_001.png ... normal_005.png
  minor/
    minor_001.png ... minor_005.png
  major/
    major_001.png ... major_005.png
  critical/
    critical_001.png ... critical_005.png

ct/
  normal/ ... critical/
    (same structure)

mri/
  normal/ ... critical/
    (same structure)

index.json                   # Master index of all images with metadata
```

- Seeded via `POST /seed/images`
- Placeholder grayscale PNGs (256x256) with chest X-ray-like patterns
- In production, replace with actual NIH ChestX-ray14 dataset images (CC0 Public Domain)
- Each image has S3 metadata: `description`, `finding`, `severity`, `modality`, `source`, `license`
