# Code Walkthrough

This document walks through each Lambda function, explaining the key logic and design decisions.

---

## CDK Infrastructure

### `bin/medical_reports-service.ts`
Entry point for the CDK app. Creates the stack with a hardcoded region (the only region reference in the codebase — all resource names are dynamically generated).

### `lib/medical_reports-service-stack.ts`
Single-file infrastructure definition (~460 lines). Creates everything: 3 DynamoDB tables, 5 GSIs, 2 S3 buckets, 12 Lambda functions, API Gateway, and IAM permissions. All resource names use the `medgemma-challenge` prefix with `${this.account}` for uniqueness.

Key patterns:
- `NodejsFunction` for automatic esbuild bundling (no Webpack config needed)
- `bundlingOptions.externalModules: ['@aws-sdk/*']` — AWS SDK v3 is already in the Lambda runtime
- `grantReadData` / `grantReadWriteData` for least-privilege IAM

---

## Report Generation

### `lambda/reports/generate/index.js` (~960 lines)

The largest and most complex Lambda. Generates realistic medical reports across 7 types.

**Lab Reports (BMP, CBC, CMP, Lipid, A1C, Thyroid, PSA, Liver):**
- Each panel defines tests with normal/minor/major ranges
- `generateLabValue()` picks values within the range matching the severity
- 70% of individual tests match the report severity, 30% get independent severity (realistic variance)
- CBC uses a special `generateCBCResults()` that calculates derived values (Hematocrit = Hemoglobin x 3, MCV = Hct/RBC x 10, etc.) with 3% physiological jitter
- PSA is excluded for female patients

**Radiology Reports (X-ray, CT, MRI, MRA, PET):**
- `radiologyFindings` object maps each modality to severity-specific finding text
- `youngAdultFindings` provides age-appropriate alternatives for patients < 45 years old:
  - MRA: Fibromuscular dysplasia instead of atherosclerotic stenosis
  - CT: AVM rupture instead of aortic aneurysm
- `generateRadiologyReport()` selects findings, fetches real medical images from S3
- PDF includes findings, impression, technique, and electronic signature

**Medical Image Retrieval:**
- `getMedicalImage()` lists images in `{modality}/{severity}/` prefix in S3
- Selects random image from available pool
- Falls back to `normal` severity if requested severity has no images
- Returns image buffer and provenance metadata (dataset, license)

**Pathology Reports:**
- Specimen types are sex-appropriate (prostate for M, breast/cervical for F)
- Includes gross description, microscopic description, and diagnosis sections

**PDF Generation:**
- Uses PDFKit with Helvetica font family
- Lab PDFs include tabular results with H/L flags in red/blue
- Radiology PDFs include structured sections (history, technique, findings, impression)
- All PDFs uploaded to S3 under `reports/{patient_id}/{report_id}.pdf`

---

## Patient Note Intake

### `lambda/notes/receive/index.js` (~383 lines)

Twilio webhook handler that receives patient SMS and extracts structured medical data.

**Flow:**
1. Parse Twilio's `application/x-www-form-urlencoded` body (handles base64 encoding)
2. Extract `From` phone number and `Body` text
3. Lookup patient via `cell-phone-index` GSI with phone format normalization:
   - Strips non-digits, takes last 10 digits
   - Tries three formats: `5551234567`, `555-123-4567`, `(555) 123-4567`
4. Call Bedrock Claude Haiku (`anthropic.claude-3-haiku-20240307-v1:0`) with extraction prompt
5. Parse JSON from Haiku's response
6. Validate all extracted values against medical ranges:
   - Temperature: 90-115 F
   - Pain scale: 0-10
   - SpO2: 50-100%
   - Systolic BP: 50-300 mmHg
   - Diastolic BP: 30-200 mmHg
   - Weight: 1-1000 lbs
   - Blood sugar: 20-800 mg/dL
   - Heart rate: 20-300 bpm
   - HbA1c: 3-20%
7. Store validated data in DynamoDB with `processed: "false"`
8. Return TwiML XML response to patient

**Bedrock Configuration:**
- Model: Claude 3 Haiku (fastest, cheapest — extraction doesn't need heavy reasoning)
- Temperature: 0.1 (low for consistent extraction)
- Max tokens: 512 (extraction output is small)
- Prompt instructs handling of colloquial health terms ("my sugar", "a-one-c", "pulse ox")

### `lambda/notes/generate/index.js` (~371 lines)

Test data generator that creates realistic patient notes from templates.

**Template Structure:**
- 4 severity levels x 4-5 templates each = 17 templates
- Templates contain placeholder tokens: `{glucose}`, `{temp}`, `{pain}`, `{systolic}`, `{diastolic}`, `{sp02}`, `{weight}`, `{a1c}`, `{hr}`
- Each template specifies value ranges, symptoms, and urgency indicators
- Values are generated within medically-appropriate ranges for each severity

**Severity Distribution:** 40% normal, 25% minor, 20% major, 15% critical

**Examples:**
- Normal: "Just checking in, feeling good today. My sugar this morning was 95 and I took my meds."
- Critical: "Having chest pain and trouble breathing. Pain is 9/10. Heart racing. Very scared."

---

## Pending Queues

### `lambda/reports/pending/index.js` (~84 lines)

Queries the `report_final_ind-index` GSI for `report_final_ind = "false"`, sorted by `created_at` ascending (oldest first). Generates presigned S3 URLs for both PDF and image with 4-hour TTL (increased from 1 hour to support longer processing times on DGX Spark).

### `lambda/notes/pending/index.js` (~112 lines)

Queries the `processed-index` GSI for `processed = "false"`, sorted by `created_at` ascending. Uses `ExpressionAttributeNames` because `processed` is a DynamoDB reserved keyword. Formats response to include all extracted vitals and a `report_type: "patient_note"` field for edge pipeline routing.

**Key difference from reports/pending:** No presigned URLs (notes are text-only), but includes pre-extracted vitals from the Bedrock Haiku extraction.

---

## Update / Mark Processed

### `lambda/reports/update/index.js` (~113 lines)

Marks a report as processed. Uses GSI-backed lookup:

1. Query `report_id-index` with the report_id to get `patient_id` (the partition key)
2. Build dynamic UpdateExpression — always sets `report_final_ind = "true"` and `processed_at`
3. Optionally adds `ai_summary`, `ai_severity`, `ai_urgency_score`, `ai_priority_level` from request body
4. Execute UpdateCommand with composite key (`patient_id` + `report_id`)

**Why GSI instead of Scan?** DynamoDB's Scan paginates at 1 MB. An unpaginated Scan silently stops returning results beyond the first page. This caused reports to return 404 even though they existed — the edge code then re-queued them, causing duplicate processing.

### `lambda/notes/update/index.js` (~149 lines)

Same pattern as report update but with different AI result fields:

1. Query `note_id-index` to get composite key
2. Always sets `processed = "true"` and `processed_at`
3. Uses `ExpressionAttributeNames` for the reserved keyword `processed`
4. Optionally adds `ai_priority_score`, `ai_interpretation`, `alert_level`, `alert_sent`

---

## Data Seeding

### `lambda/seed/index.js` (~146 lines)

Seeds the patient-master table with 100 patients:
- Realistic names from common US first/last name pools (20 male, 20 female, 30 last names)
- Ages 18-85 (random DOB)
- 50/50 male/female split
- Addresses from 20 major US cities with real ZIP codes
- Phone numbers in XXX-XXX-XXXX format
- Batch writes in groups of 25 (DynamoDB limit)
- Idempotent: skips if table already has data

### `lambda/seed-images/index.js` (~395 lines)

Seeds the medical-images S3 bucket:
- Creates 60 placeholder images (3 modalities x 4 severities x 5 images each)
- 256x256 grayscale PNGs generated procedurally:
  - Chest-like oval shape with rib banding pattern
  - Heart shadow in center-left
  - Pathology spots for non-normal severities (larger for higher severity)
- Creates a CRC32-valid PNG from scratch (no image library dependency)
- Uploads with S3 metadata: description, finding, severity, modality, source, license
- Creates an `index.json` manifest
- Idempotent: skips if images already exist

---

## Utility Lambdas

### `lambda/patients/list/index.js` (~59 lines)
Simple paginated Scan on patient-master. Supports `limit` and `lastKey` query parameters.

### `lambda/patients/get/index.js` (~59 lines)
Direct GetCommand lookup by patient_id. Returns 404 if not found.

### `lambda/reports/get/index.js` (~90 lines)
Queries patient-results by patient_id (partition key query, not scan). Generates 1-hour presigned URLs for PDFs and images. Returns results newest-first.

---

## Dependencies

From `package.json`:

| Package | Purpose |
|---------|---------|
| `aws-cdk-lib` | CDK infrastructure definitions |
| `constructs` | CDK construct base class |
| `@aws-sdk/client-dynamodb` | DynamoDB low-level client |
| `@aws-sdk/lib-dynamodb` | DynamoDB document client (JSON marshalling) |
| `@aws-sdk/client-s3` | S3 operations |
| `@aws-sdk/s3-request-presigner` | Presigned URL generation |
| `@aws-sdk/client-bedrock-runtime` | Bedrock Claude Haiku invocation |
| `pdfkit` | PDF generation (lab/radiology/pathology reports) |
| `uuid` | UUID v4 generation for report/note IDs |
| `typescript` | TypeScript compilation (CDK stack) |
| `esbuild` | Lambda bundling (used by NodejsFunction) |
| `jest` / `ts-jest` | Testing framework |
