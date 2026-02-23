# MedGemma Triage System - Deployment Guide

This document explains how to deploy the MedGemma Triage System to DGX Spark running K3s Kubernetes.

## Target Environment

| Component | Specification |
|-----------|---------------|
| Hardware | NVIDIA DGX Spark (GB10) |
| OS | Ubuntu with NVIDIA drivers |
| Kubernetes | K3s (lightweight K8s) |
| GPU Memory | 128GB total |
| SSH | `ssh <your-spark-host>` (<your-spark-ip>) |

---

## System Architecture Overview

The MedGemma Triage System uses a **microservices architecture** with three distinct application pods that communicate via Redis queues:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DGX SPARK (K3s Cluster)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  SCHEDULER POD  │  │   WORKER POD    │  │    API POD      │             │
│  │  (APScheduler)  │  │  (LangGraph)    │  │   (FastAPI)     │             │
│  │                 │  │                 │  │                 │             │
│  │  - Poll AWS API │  │  - 8-step       │  │  - /health      │             │
│  │  - Backpressure │  │    pipeline     │  │  - /process     │             │
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
│  │  - Lab analysis             │  │  - Image analysis           │          │
│  │  - Pathology analysis       │  │  - X-ray, CT, MRI, PET      │          │
│  │  - Radiology synthesis      │  │  - Radiology findings       │          │
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
│  - GET  /patients/:id        → Patient demographics                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Microservice Components

### 1. APScheduler Service (Scheduler Pod)

**Purpose:** Polls the AWS backend API for new medical reports and patient notes, then queues them to Redis for processing.

**Source Code:** `src/scheduler/report_poller.py`

**Key Features:**
- Uses APScheduler with AsyncIOScheduler for interval-based polling
- Polls every 60 seconds (configurable via `POLL_INTERVAL_SECONDS`)
- Backpressure: checks combined Redis queue depth before each poll; skips if at/above threshold (configurable via `QUEUE_BACKPRESSURE_THRESHOLD`, default 20). Resumes automatically when worker drains the queues.
- Uses Redis distributed lock to prevent duplicate polling if multiple replicas exist
- Queues reports to `medgemma:report_queue` and notes to `medgemma:note_queue`
- FIFO ordering (oldest reports processed first)

**Queue Message Format:**
```json
{
  "type": "report",
  "tenant_id": "practice-001",
  "report_id": "uuid-here",
  "patient_id": 42,
  "report_type": "lab|xray|ct|mri|path",
  "pdf_url": "https://s3-presigned-url...",
  "image_url": "https://s3-presigned-url...",
  "severity": "normal|minor|major|critical",
  "queued_at": "2026-02-11T10:30:00Z"
}
```

**K8s Deployment:** `k8s/scheduler-deployment.yaml`
```yaml
spec:
  replicas: 1  # MUST be 1 to avoid duplicate polling
  template:
    spec:
      hostNetwork: true  # Access model servers on host
      containers:
      - name: scheduler
        command: ["python", "-m", "src.scheduler.report_poller"]
        resources:
          requests: { memory: "256Mi", cpu: "250m" }
          limits: { memory: "1Gi", cpu: "1000m" }
```

---

### 2. REST API Puller (AWS API Client)

**Purpose:** HTTP client that fetches pending reports and patient data from the AWS backend service.

**Source Code:** `src/clients/aws_api.py`

**Key Endpoints Called:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/reports/pending?limit=50` | Fetch unprocessed medical reports |
| `GET` | `/notes/pending?limit=50` | Fetch unprocessed patient notes |
| `GET` | `/patients/{id}` | Fetch patient demographics |
| `PATCH` | `/reports/update/{report_id}` | Mark report as processed |
| `PATCH` | `/notes/update/{note_id}` | Mark note as processed |

**AWS API Base URL:** `https://<your-api-id>.execute-api.<region>.amazonaws.com/prod`

**Report Types Returned:**
| Type | Description | Has Image? | Model Flow |
|------|-------------|------------|------------|
| `lab` | Blood tests (BMP, CBC, A1C, etc.) | No | 27B only |
| `path` | Pathology/biopsies | No | 27B only |
| `xray` | Chest X-rays | Yes | 27B → 4B (image) → 27B |
| `ct` | CT scans | Yes | 27B → 4B (image) → 27B |
| `mri` | MRI scans | Yes | 27B → 4B (image) → 27B |
| `mra` | MR Angiography | Yes | 27B → 4B (image) → 27B |
| `pet` | PET scans | Yes | 27B → 4B (image) → 27B |

**Model Responsibilities:**
- **MedGemma 27B**: Primary model for ALL text analysis - classification, extraction, routing, and final analysis
- **MedGemma 4B**: ONLY used for radiology image analysis (multimodal)

---

### 3. LangGraph Pipeline (Worker Pod)

**Purpose:** Consumes reports from Redis queue and processes them through an intelligent 8-step AI analysis pipeline.

**Source Code:** `src/worker/pipeline_worker.py`

**Key Features:**
- Consumes from Redis queues using RPOP (FIFO)
- Reports have priority over notes
- Initializes all AI clients (MedGemma 27B, 4B, LOINC, MongoDB)
- Graceful shutdown handling with signal handlers
- Configurable concurrency (default: 1 to avoid model server race conditions)

**Pipeline Steps:**
1. **Intake** - Download PDF/image from S3 pre-signed URLs
2. **Classify** - MedGemma 27B determines report type
3. **Extract** - MedGemma 27B extracts lab values, maps to LOINC
4. **Patient Context** - Fetch demographics from MongoDB
5. **Historical** - Analyze trends from prior results (evidence-based RCV thresholds from Westgard biological variation data)
6. **Analyze** - MedGemma 27B analysis (calls 4B for radiology images)
7. **Score** - Calculate priority score (0-100)
8. **Notify** - Send alerts, persist results to MongoDB

**Radiology Analysis Flow (Step 6):**
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  MedGemma 27B   │     │  MedGemma 4B    │     │  MedGemma 27B   │
│  (Evaluation)   │────►│  (Multimodal)   │────►│  (Synthesis)    │
│                 │     │                 │     │                 │
│  Determines     │     │  Image Analysis │     │  Final Summary  │
│  radiology type │     │  → Findings     │     │  + Clinical Score│
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**K8s Deployment:** `k8s/worker-deployment.yaml`
```yaml
spec:
  replicas: 1  # Single worker to avoid model server race conditions
  template:
    spec:
      hostNetwork: true  # Access model servers on host
      containers:
      - name: worker
        command: ["python", "-m", "src.worker.pipeline_worker"]
        env:
        - name: WORKER_CONCURRENCY
          value: "1"
        resources:
          requests: { memory: "512Mi", cpu: "500m" }
          limits: { memory: "2Gi", cpu: "2000m" }
```

---

### 4. FastAPI REST Service (API Pod)

**Purpose:** Provides REST endpoints for health checks, manual triggers, and status queries.

**Source Code:** `src/api/routes.py` and `main.py`

**Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check (returns 200 if healthy) |
| `/health/detailed` | GET | Detailed status of all services and dependencies |
| `/process/{report_id}` | POST | Manual trigger to process a specific report |
| `/status/{report_id}` | GET | Get processing status for a report |
| `/queue/stats` | GET | Redis queue statistics |

**K8s Deployment:** `k8s/api-deployment.yaml`
```yaml
spec:
  replicas: 2  # Can scale horizontally
  template:
    spec:
      hostNetwork: false  # API doesn't need host network
      containers:
      - name: api
        command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet: { path: /health, port: 8000 }
        readinessProbe:
          httpGet: { path: /health, port: 8000 }
```

**NodePort Service:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: triage-api
spec:
  type: NodePort
  ports:
  - port: 8000
    targetPort: 8000
    nodePort: 30800  # Accessible at http://<your-spark-ip>:30800
```

---

## Data Flow

```
AWS API                Redis Queue              Worker                MongoDB
   │                       │                      │                      │
   │  GET /reports/pending │                      │                      │
   │◄──────────────────────│                      │                      │
   │                       │  Backpressure check  │                      │
   │                       │  (skip if depth ≥20) │                      │
   │  [reports]            │                      │                      │
   │──────────────────────►│  LPUSH report_queue  │                      │
   │                       │◄─────────────────────│                      │
   │                       │                      │                      │
   │                       │  RPOP report_queue   │                      │
   │                       │─────────────────────►│                      │
   │                       │                      │                      │
   │                       │                      │  Run 8-Step Pipeline │
   │                       │                      │─────────────────────►│
   │                       │                      │                      │
   │  PATCH /reports/update│                      │  Store Results       │
   │◄──────────────────────│──────────────────────│◄─────────────────────│
```

---

## ConfigMap Network Configuration

**Important:** The scheduler and worker pods use `hostNetwork: true` to access model servers on the host. The configmap uses K8s ClusterIP service names for infrastructure:

```yaml
# In configmap.yaml - uses ClusterIP service names
REDIS_URL: "redis://redis:6379"
MONGODB_URI: "mongodb://mongodb:27017"
```

Since pods with `hostNetwork: true` can still resolve ClusterIP services via K8s DNS (`ClusterFirstWithHostNet` DNS policy), this configuration works correctly.

**Alternative (NodePort):** If DNS resolution fails, update configmap to use NodePort addresses:
```yaml
REDIS_URL: "redis://localhost:30379"
MONGODB_URI: "mongodb://localhost:30017"
OPENSEARCH_URL: "http://localhost:30920"
```

---

## Prerequisites

### 1. SSH Access
```bash
# Add to ~/.ssh/config
Host <your-spark-host>
    HostName <your-spark-ip>
    User <your-username>
    IdentityFile ~/.ssh/id_rsa
```

### 2. K3s Cluster Running
```bash
ssh <your-spark-host>
kubectl get nodes
# Should show: <your-spark-host>   Ready   control-plane,master
```

### 3. Infrastructure Pods Running
```bash
kubectl get pods -n medgemma-triage
# Should show: mongodb, redis, opensearch pods running
```

### 4. Model Servers Running on Host

**MedGemma 27B (Port 8357):**
```bash
ssh <your-spark-host>
cd ~/medgemma-server
export HF_TOKEN="your-huggingface-token"
nohup python3 serve_medgemma_stream.py > medgemma_27b.log 2>&1 &
```

**MedGemma 4B (Port 8358):**
```bash
ssh <your-spark-host>
cd ~/medgemma-server
export HF_TOKEN="your-huggingface-token"
nohup python3 serve_medgemma_4b.py > medgemma_4b.log 2>&1 &
```

**Why Model Servers Run on Host (Not in K3s):**
1. **GB10 GPU Support:** Requires PyTorch nightly (cu128) not available in NVIDIA containers
2. **vLLM Incompatibility:** MedSigLIP has head_dim=72 which flash attention doesn't support
3. **Memory Management:** Direct GPU access allows better allocation

---

## Current Deployment Status

| Component | Status | Notes |
|-----------|--------|-------|
| MongoDB | ✅ Running | K3s pod, NodePort 30017 |
| Redis | ✅ Running | K3s pod, NodePort 30379 |
| OpenSearch | ✅ Running | K3s pod, NodePort 30920 |
| MedGemma 27B | ✅ Running | Host port 8357 |
| MedGemma 4B | ✅ Running | Host port 8358 |
| Scheduler Pod | ✅ Running | Polling every 60s, backpressure active |
| Worker Pod | ✅ Running | Processing 8-step pipeline |
| API Pod | ✅ Running (x2) | NodePort 30800, health OK |

---

## Deployment Steps

### Step 1: Sync Code to Spark

```bash
# From Windows development machine
scp -r KaggleChallenge/medical-agent <your-spark-host>:~/
```

### Step 2: Build Docker Image

```bash
ssh <your-spark-host>
cd ~/medical-agent

# Build for ARM64 (Spark is ARM-based)
docker build -t medgemma-triage:latest .

# Import into K3s containerd
docker save medgemma-triage:latest | sudo k3s ctr images import -
```

### Step 3: Create Namespace and Config

```bash
# Create namespace (if not exists)
kubectl create namespace medgemma-triage --dry-run=client -o yaml | kubectl apply -f -

# Apply ConfigMap
kubectl apply -f k8s/configmap.yaml

# Create secrets from example (edit with real values first!)
cp k8s/secrets.yaml.example k8s/secrets.yaml
# Edit k8s/secrets.yaml with actual credentials
kubectl apply -f k8s/secrets.yaml
```

### Step 4: Deploy Application Pods

```bash
# Deploy API first (for health checks)
kubectl apply -f k8s/api-deployment.yaml

# Deploy Worker (LangGraph pipeline)
kubectl apply -f k8s/worker-deployment.yaml

# Deploy Scheduler (starts polling - deploy last!)
kubectl apply -f k8s/scheduler-deployment.yaml
```

### Step 5: Verify Deployment

```bash
# Check all pods
kubectl get pods -n medgemma-triage

# Expected output:
# NAME                                READY   STATUS    RESTARTS   AGE
# triage-api-xxxxx                    1/1     Running   0          1m
# triage-api-yyyyy                    1/1     Running   0          1m
# pipeline-worker-xxxxx               1/1     Running   0          1m
# report-scheduler-xxxxx              1/1     Running   0          1m
# mongodb-xxxxx                       1/1     Running   0          1d
# redis-xxxxx                         1/1     Running   0          1d
# opensearch-xxxxx                    1/1     Running   0          1d

# Check services
kubectl get svc -n medgemma-triage
```

---

## Quick Deploy Script

Create `deploy-all.sh`:
```bash
#!/bin/bash
set -e

echo "=== Syncing code to Spark ==="
scp -r . <your-spark-host>:~/medical-agent/

echo "=== Building image on Spark ==="
ssh <your-spark-host> "cd ~/medical-agent && docker build -t medgemma-triage:latest ."

echo "=== Importing to K3s ==="
ssh <your-spark-host> "docker save medgemma-triage:latest | sudo k3s ctr images import -"

echo "=== Applying manifests ==="
ssh <your-spark-host> "kubectl apply -f ~/medical-agent/k8s/"

echo "=== Restarting deployments ==="
ssh <your-spark-host> "kubectl rollout restart deployment -n medgemma-triage"

echo "=== Waiting for rollout ==="
ssh <your-spark-host> "kubectl rollout status deployment/triage-api -n medgemma-triage"
ssh <your-spark-host> "kubectl rollout status deployment/pipeline-worker -n medgemma-triage"
ssh <your-spark-host> "kubectl rollout status deployment/report-scheduler -n medgemma-triage"

echo "=== Deployment complete ==="
ssh <your-spark-host> "kubectl get pods -n medgemma-triage"
```

---

## Kubernetes Manifests Reference

| File | Description |
|------|-------------|
| `k8s/namespace.yaml` | Creates `medgemma-triage` namespace |
| `k8s/configmap.yaml` | Non-sensitive configuration (URLs, thresholds) |
| `k8s/secrets.yaml.example` | Template for sensitive credentials (copy to secrets.yaml) |
| `k8s/mongodb.yaml` | MongoDB StatefulSet + Service |
| `k8s/redis.yaml` | Redis Deployment + Service |
| `k8s/opensearch.yaml` | OpenSearch + Dashboards |
| `k8s/scheduler-deployment.yaml` | APScheduler pod (1 replica) |
| `k8s/worker-deployment.yaml` | LangGraph pipeline worker (1 replica) |
| `k8s/api-deployment.yaml` | FastAPI pod + NodePort Service (2 replicas) |

---

## Accessing the Service

### Health Check
```bash
# From Spark host
curl http://localhost:30800/health

# From remote (via SSH tunnel)
ssh -L 8000:localhost:30800 <your-spark-host>
curl http://localhost:8000/health
```

### API Endpoints
```bash
# Basic health
curl http://<your-spark-ip>:30800/health

# Detailed health (shows all dependencies)
curl http://<your-spark-ip>:30800/health/detailed

# Queue statistics
curl http://<your-spark-ip>:30800/queue/stats

# Manual trigger
curl -X POST http://<your-spark-ip>:30800/process/{report_id}
```

---

## Monitoring

### View Logs
```bash
# Scheduler logs (polling activity)
kubectl logs -f deployment/report-scheduler -n medgemma-triage

# Worker logs (pipeline processing)
kubectl logs -f deployment/pipeline-worker -n medgemma-triage

# API logs
kubectl logs -f deployment/triage-api -n medgemma-triage
```

### Check Queue Status
```bash
# Connect to Redis
kubectl exec -it deployment/redis -n medgemma-triage -- redis-cli

# Check queue lengths
LLEN medgemma:report_queue
LLEN medgemma:note_queue

# Check if lock is held
GET medgemma:poll_lock
```

### Model Server Health
```bash
# MedGemma 27B
curl http://<your-spark-host>:8357/health

# MedGemma 4B
curl http://<your-spark-host>:8358/health
```

---

## Troubleshooting

### Pod Not Starting
```bash
kubectl describe pod -l app=report-scheduler -n medgemma-triage
kubectl get events -n medgemma-triage --sort-by='.lastTimestamp'
```

### Cannot Connect to Model Servers
Pods use `hostNetwork: true` to access model servers. Verify:
```bash
kubectl exec -it deployment/pipeline-worker -n medgemma-triage -- curl http://localhost:8357/health
```

### Queue Not Processing
```bash
# Check scheduler is polling
kubectl logs deployment/report-scheduler -n medgemma-triage | grep "pending reports"

# Check worker is consuming
kubectl logs deployment/pipeline-worker -n medgemma-triage | grep "Processing"

# Check for errors
kubectl logs deployment/pipeline-worker -n medgemma-triage | grep -i error
```

### Image Not Found
```bash
# Verify image is imported
ssh <your-spark-host> "sudo k3s ctr images list | grep medgemma-triage"
```

---

## Scaling Guidelines

```bash
# Scale API pods (SAFE to scale)
kubectl scale deployment/triage-api -n medgemma-triage --replicas=3

# DO NOT scale scheduler beyond 1 (causes duplicate polling)
# DO NOT scale worker beyond 1 (model servers can't handle concurrent requests)
```

---

## Rollback

```bash
kubectl rollout undo deployment/triage-api -n medgemma-triage
kubectl rollout undo deployment/pipeline-worker -n medgemma-triage
kubectl rollout undo deployment/report-scheduler -n medgemma-triage
```

---

## Cleanup

```bash
# Delete application pods only
kubectl delete deployment report-scheduler pipeline-worker triage-api -n medgemma-triage

# Delete everything (including infrastructure)
kubectl delete namespace medgemma-triage
```
