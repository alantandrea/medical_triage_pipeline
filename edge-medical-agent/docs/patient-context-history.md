# Patient Context History in Email Notifications

## Overview

When a doctor receives an urgent or important email notification from the MedGemma Triage System, the email now includes a "Patient History" section at the bottom. This table shows the patient's recent reports and notes already on file, giving the doctor immediate context without having to dig through the chart.

The goal is to reduce doctor burnout by putting everything they need in one place — the current alert plus the patient's recent history — so they can quickly assess the situation and make informed decisions.

## Design

### What Gets Included

The Patient History table pulls from two MongoDB collections:

| Source | Collection | What's Shown |
|--------|-----------|--------------|
| Lab/Radiology/Pathology Reports | `processed_reports` | Date, score, first finding summary |
| Patient Notes (SMS/self-reported) | `processed_notes` | Date, score, analysis summary |

Items are sorted newest-first, limited to the 10 most recent entries. The current report/note being emailed is excluded from the history to avoid redundancy.

### When It Appears

Patient history is only fetched and included for urgent and important emails (score >= 50). Routine and followup reports don't trigger emails, so no history is needed.

### How It Looks

The history appears as an HTML table at the bottom of the email, below the current findings and recommendations:

```
📂 Patient History
Recent reports and notes on file for this patient.

| Date                | Type      | Score | Summary                                    |
|---------------------|-----------|-------|--------------------------------------------|
| 2026-02-18 16:45:10 | 📋 Report | 100   | Pituitary apoplexy                         |
| 2026-02-18 14:41:35 | 📋 Report | 65    | High Platelet Count: 751 K/uL             |
| 2026-02-18 21:03:13 | 💬 Note   | 10    | Home A1C test: 5.2%, feeling well          |
```

Scores are color-coded:
- Red (>= 70): Critical/urgent findings
- Orange (>= 50): Important findings
- Blue (>= 30): Follow-up items
- Green (< 30): Routine/normal

### Example: Patient 57 (Joshua Martin, 36M)

If the doctor receives the score-100 "widespread metastatic disease" PET scan alert, the Patient History section would show:

| Date | Type | Score | Summary |
|------|------|-------|---------|
| 2026-02-18 16:36 | 📋 Report | 40 | Low-grade uptake in a pulmonary nodule on PET scan |
| 2026-02-18 16:28 | 📋 Report | 0 | Renal arteries appear normal |
| 2026-02-18 19:36 | 💬 Note | 20 | Fatigue, aches, low-grade fever 99.3°F |
| 2026-02-18 17:37 | 💬 Note | 10 | Morning blood sugar 107 mg/dL, feeling well |

The doctor immediately sees the earlier pulmonary nodule finding — critical context for understanding the progression to metastasis.

## Implementation

### Files Modified

| File | Change |
|------|--------|
| `src/clients/mongodb_client.py` | Added `get_patient_history()` method |
| `src/reporting/service.py` | Added `_build_patient_history_html()` helper; updated `send_urgent_alert()` and `send_important_notification()` to accept and render `patient_history` parameter |
| `src/pipeline/nodes/notify.py` | Fetches patient history before sending emails for urgent/important reports |
| `src/worker/pipeline_worker.py` | Fetches patient history before sending emails for urgent/important notes |

### Data Flow

```
Report/Note processed
    │
    ▼
Score calculated
    │
    ├── Score < 50 → No email, no history fetch
    │
    ├── Score >= 50 → Fetch patient history from MongoDB
    │                   (processed_reports + processed_notes)
    │                   Exclude current item
    │                   Limit 10, newest first
    │
    ▼
Email sent with Patient History table appended
```

### MongoDB Query

The `get_patient_history` method runs two queries:
1. `processed_reports.find({tenant_id, patient_id, report_id != current}).sort(processed_at, -1).limit(10)`
2. `processed_notes.find({tenant_id, patient_id}).sort(processed_at, -1).limit(10)`

Results are merged, sorted by date descending, and capped at 10 total items.

### Error Handling

If the history fetch fails (MongoDB timeout, etc.), the email is still sent without the history section. This is non-blocking — the current alert is always the priority.
