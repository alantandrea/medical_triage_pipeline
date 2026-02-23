# API Reference

Base URL: `https://<api-id>.execute-api.<region>.amazonaws.com/prod`

All endpoints return JSON with `Content-Type: application/json` and `Access-Control-Allow-Origin: *`.

---

## Patients

### GET /patients

List all patients with pagination.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | number | 100 | Max patients per page |
| `lastKey` | string | — | URL-encoded pagination key from previous response |

**Response (200):**
```json
{
  "patients": [
    {
      "patient_id": 1,
      "first_name": "James",
      "last_name": "Smith",
      "patient_dob": "1965-03-15",
      "sex": "M",
      "cell_phone": "555-123-4567",
      "home_phone": "555-234-5678",
      "work_phone": "555-345-6789",
      "address_1": "123 Main St",
      "address_2": "",
      "city": "New York",
      "state": "NY",
      "zipcode": "10001"
    }
  ],
  "count": 100,
  "lastKey": "<pagination-token>"
}
```

### GET /patients/{id}

Get a specific patient by ID.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | number | Patient ID (1-100 for seeded data) |

**Response (200):** Single patient object (same fields as above).

**Response (404):** `{ "error": "Patient not found" }`

---

## Reports

### POST /reports/generate

Generate a random medical report for a random patient.

**Response (200):**
```json
{
  "message": "Report generated successfully",
  "report": {
    "patient_id": 42,
    "report_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "report_date": "2026-02-19",
    "report_type": "xray",
    "reporting_source": "Regional Medical Imaging Center",
    "report_pdf_s3_key": "reports/42/a1b2c3d4.pdf",
    "report_image_s3_key": "images/42/a1b2c3d4.png",
    "report_final_ind": "false",
    "created_at": "2026-02-19T10:30:00.000Z",
    "severity": "major",
    "image_source": {
      "dataset": "medical_dataset",
      "license": "CC0/CC-BY (Public Dataset)",
      "modality": "xray"
    }
  },
  "patient": {
    "patient_id": 42,
    "first_name": "James",
    "last_name": "Smith"
  }
}
```

### POST /reports/generate/{patient_id}

Generate a report for a specific patient.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `patient_id` | number | Target patient ID |

**Response:** Same as `POST /reports/generate`.

### GET /reports/{patient_id}

Get all reports for a patient with presigned S3 URLs.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `patient_id` | number | Patient ID |

**Response (200):**
```json
{
  "patient_id": 42,
  "reports": [
    {
      "patient_id": 42,
      "report_id": "...",
      "report_type": "lab",
      "severity": "normal",
      "report_pdf_url": "https://s3.amazonaws.com/...?X-Amz-Signature=...",
      "report_image_url": null,
      "report_final_ind": "true",
      "created_at": "2026-02-18T..."
    }
  ],
  "count": 5
}
```

Presigned URLs expire in **1 hour**.

### GET /reports/pending

Get unprocessed reports for the AI pipeline to consume.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | number | 50 | Max reports to return |

**Response (200):**
```json
{
  "pending_reports": [
    {
      "patient_id": 42,
      "report_id": "...",
      "report_type": "xray",
      "severity": "major",
      "report_pdf_s3_key": "reports/42/...",
      "report_pdf_url": "https://...presigned...",
      "report_image_s3_key": "images/42/...",
      "report_image_url": "https://...presigned...",
      "report_final_ind": "false",
      "created_at": "2026-02-19T..."
    }
  ],
  "count": 10
}
```

Presigned URLs expire in **4 hours** (longer TTL for pipeline processing).

Reports are returned **oldest first** (FIFO) to ensure fair processing order.

### PATCH /reports/update/{report_id}

Mark a report as processed by the AI pipeline.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `report_id` | string (UUID) | Report identifier |

**Request Body (optional):**
```json
{
  "ai_summary": "Normal chest X-ray with no acute findings.",
  "ai_severity": "normal",
  "ai_urgency_score": 0.15,
  "ai_priority_level": "routine"
}
```

**Response (200):**
```json
{
  "message": "Report marked as processed",
  "report": { ... full updated report ... }
}
```

**Response (404):** `{ "error": "Report not found" }`

**Implementation note:** Uses GSI `report_id-index` for O(1) lookup instead of table Scan.

---

## Notes

### POST /notes

Receive a patient SMS via Twilio webhook. This is called by Twilio when a patient texts the configured phone number.

**Request Body:** `application/x-www-form-urlencoded` (Twilio format)
| Field | Description |
|-------|-------------|
| `From` | Patient phone number (e.g., `+15551234567`) |
| `Body` | SMS message text |

**Processing:**
1. Lookup patient by phone number (tries multiple formats)
2. Extract structured vitals using Bedrock Claude Haiku
3. Validate ranges (temp 90-115F, SpO2 50-100%, BP reasonable, etc.)
4. Store in DynamoDB with `processed: "false"`

**Response (200):** TwiML XML confirming receipt.

### POST /notes/generate

Generate a sample patient note for testing. Uses severity-weighted templates with realistic medical content.

**Response (200):**
```json
{
  "message": "Patient note generated successfully",
  "note": {
    "note_id": "...",
    "patient_id": 42,
    "patient_name": "James Smith",
    "severity": "major",
    "note_text": "Not feeling well at all. Temp is 101.2 and I have pain in my stomach area, about 6/10.",
    "vitals": {
      "temperature": 101.2,
      "pain_scale": 6
    },
    "symptoms": ["abdominal pain", "fever"],
    "urgency_indicators": ["persistent abdominal pain"],
    "has_urgency": true
  }
}
```

### POST /notes/generate/{patient_id}

Generate a note for a specific patient.

### GET /notes/pending

Get unprocessed patient notes for the AI pipeline.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | number | 50 | Max notes to return |

**Response (200):**
```json
{
  "pending_notes": [
    {
      "patient_id": 42,
      "note_id": "...",
      "patient_name": "James Smith",
      "note_date": "2026-02-19T...",
      "note_text": "My sugar was 250 this morning...",
      "temperature": null,
      "pain_scale": null,
      "sp02": null,
      "systolic": null,
      "diastolic": null,
      "weight": null,
      "blood_sugar_level": 250,
      "heart_rate": null,
      "hemoglobin_a1c": null,
      "symptoms": ["dizziness", "nausea", "hyperglycemia"],
      "urgency_indicators": ["very high blood sugar"],
      "has_urgency": true,
      "extraction_confidence": "high",
      "values_extracted": 1,
      "processed": "false",
      "report_type": "patient_note"
    }
  ],
  "count": 5
}
```

Notes are returned **oldest first** (FIFO). The `report_type: "patient_note"` field enables the edge pipeline to route notes through the correct processing path.

### PATCH /notes/update/{note_id}

Mark a note as processed with AI analysis results.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `note_id` | string (UUID) | Note identifier |

**Request Body:**
```json
{
  "ai_priority_score": 0.85,
  "ai_interpretation": "Patient reports significantly elevated blood glucose...",
  "alert_level": "high",
  "alert_sent": true
}
```

**Response (200):**
```json
{
  "message": "Note marked as processed",
  "note_id": "...",
  "patient_id": 42,
  "processed_at": "2026-02-19T15:30:00.000Z"
}
```

**Response (404):** `{ "error": "Note not found", "note_id": "..." }`

**Implementation note:** Uses GSI `note_id-index` for O(1) lookup instead of table Scan.

---

## Seed / Setup

### POST /seed

Seed the patient-master table with 100 sample patients. Idempotent — skips if data already exists.

**Response (200):**
```json
{
  "message": "Successfully seeded patients",
  "count": 100
}
```

### POST /seed/images

Seed the medical-images S3 bucket with placeholder X-ray images organized by modality and severity. Idempotent — skips if images already exist.

**Response (200):**
```json
{
  "message": "Successfully seeded medical images",
  "count": 60,
  "bucket": "medgemma-challenge-medical-images-...",
  "structure": {
    "modalities": ["xray", "ct", "mri"],
    "severities": ["normal", "minor", "major", "critical"]
  }
}
```

---

## Reports vs Notes: Key Differences

| Aspect | Reports | Notes |
|--------|---------|-------|
| **Source** | Generated by system | Patient SMS via Twilio |
| **Content** | PDF + optional image | Free-text with extracted vitals |
| **Pending field** | `report_final_ind` | `processed` |
| **Presigned URLs** | Yes (PDF + image) | No (text only) |
| **PATCH body** | `ai_summary`, `ai_severity`, `ai_urgency_score`, `ai_priority_level` | `ai_priority_score`, `ai_interpretation`, `alert_level`, `alert_sent` |
| **Edge pipeline** | 8 nodes (includes fetch, extract, analyze_image) | 5 nodes (skips fetch, extract, analyze_image) |

## Error Responses

All endpoints return standard error format:
```json
{
  "error": "Error description",
  "message": "Detailed error message (on 500s)"
}
```

| Code | Meaning |
|------|---------|
| 400 | Missing/invalid parameters |
| 404 | Resource not found |
| 500 | Internal server error |
