#!/usr/bin/env bash
###############################################################################
# MedGemma Model Server Setup
#
# Downloads and starts MedGemma model servers on the host GPU.
# Run this AFTER docker-compose is up (infrastructure services).
#
# Prerequisites:
#   - NVIDIA GPU with CUDA support
#   - At least 60 GB GPU memory (for 27B only) or 128 GB (for 27B + 4B)
#   - Python 3.11+
#   - HuggingFace account with HAI-DEF access approved
#     (https://huggingface.co/google/medgemma-27b-text-it)
#
# Usage:
#   export HF_TOKEN="your-huggingface-token"
#   bash setup_models.sh
#
# Options:
#   --27b-only    Skip MedGemma 4B (saves ~8 GB GPU memory)
#   --skip-install Skip pip install (if deps already installed)
###############################################################################

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────
SKIP_4B=false
SKIP_INSTALL=false
for arg in "$@"; do
    case $arg in
        --27b-only)    SKIP_4B=true ;;
        --skip-install) SKIP_INSTALL=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "=============================================="
echo "  MedGemma Model Server Setup"
echo "=============================================="
echo ""
info "First run downloads model weights from HuggingFace (~50 GB for 27B, ~8 GB for 4B)."
info "This can take 10-20 minutes depending on your connection. Subsequent starts are fast."
echo ""

# ── Check prerequisites ─────────────────────────────────────
info "Checking prerequisites..."

# Python
if ! command -v python3 &>/dev/null; then
    err "Python 3 not found. Install Python 3.11+ first."
    exit 1
fi
PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PYTHON_VER found"

# NVIDIA GPU
if ! command -v nvidia-smi &>/dev/null; then
    err "nvidia-smi not found. NVIDIA GPU drivers required."
    exit 1
fi
GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')
ok "NVIDIA GPU detected: ${GPU_MEM} MB total memory"

if [ "$GPU_MEM" -lt 55000 ]; then
    warn "Less than 55 GB GPU memory. MedGemma 27B requires ~51 GB."
    warn "Consider using a machine with more GPU memory."
fi

# HuggingFace token
if [ -z "${HF_TOKEN:-}" ]; then
    err "HF_TOKEN environment variable not set."
    echo ""
    echo "  1. Go to https://huggingface.co/settings/tokens"
    echo "  2. Create a token with 'read' access"
    echo "  3. Accept the HAI-DEF terms at https://huggingface.co/google/medgemma-27b-text-it"
    echo "  4. Run: export HF_TOKEN=\"your-token-here\""
    echo ""
    exit 1
fi
ok "HF_TOKEN is set"

# ── Create model server directory ────────────────────────────
MODEL_DIR="$HOME/medgemma-servers"
mkdir -p "$MODEL_DIR"
info "Model server directory: $MODEL_DIR"

# ── Install Python dependencies ──────────────────────────────
if [ "$SKIP_INSTALL" = false ]; then
    info "Installing Python dependencies..."

    # Detect CUDA version for PyTorch index URL
    CUDA_VER=$(nvidia-smi | grep -oP 'CUDA Version: \K[0-9]+\.[0-9]+' || echo "12.1")
    CUDA_MAJOR=$(echo "$CUDA_VER" | cut -d. -f1)
    CUDA_MINOR=$(echo "$CUDA_VER" | cut -d. -f2)

    # Use appropriate PyTorch index
    if [ "$CUDA_MAJOR" -ge 12 ] && [ "$CUDA_MINOR" -ge 8 ]; then
        # CUDA 12.8+ (Blackwell/GB10) — needs nightly
        info "CUDA $CUDA_VER detected — installing PyTorch nightly (cu128)"
        pip3 install --pre torch --index-url https://download.pytorch.org/whl/nightly/cu128
    elif [ "$CUDA_MAJOR" -ge 12 ] && [ "$CUDA_MINOR" -ge 4 ]; then
        info "CUDA $CUDA_VER detected — installing PyTorch stable (cu124)"
        pip3 install torch --index-url https://download.pytorch.org/whl/cu124
    else
        info "CUDA $CUDA_VER detected — installing PyTorch stable (cu121)"
        pip3 install torch --index-url https://download.pytorch.org/whl/cu121
    fi

    pip3 install transformers accelerate fastapi uvicorn huggingface_hub
    ok "Python dependencies installed"
else
    ok "Skipping pip install (--skip-install)"
fi

# ── Write MedGemma 27B server script ────────────────────────
cat > "$MODEL_DIR/serve_27b.py" << 'PYEOF'
"""MedGemma 27B Text IT — FastAPI model server."""
import os, torch, logging
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medgemma-27b")

app = FastAPI(title="MedGemma 27B IT")

MODEL_ID = "google/medgemma-27b-text-it"
tokenizer = None
model = None

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: List[Message]
    max_tokens: int = 2048
    temperature: float = 0.3

class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"

class ChatResponse(BaseModel):
    choices: List[Choice]

@app.on_event("startup")
async def load_model():
    global tokenizer, model
    logger.info(f"Loading {MODEL_ID}...")
    token = os.environ.get("HF_TOKEN")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=token)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, token=token,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    logger.info("Model loaded successfully")

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_ID, "loaded": model is not None}

@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    prompt_parts = []
    for msg in request.messages:
        if msg.role == "system":
            prompt_parts.append(f"<start_of_turn>system\n{msg.content}<end_of_turn>")
        elif msg.role == "user":
            prompt_parts.append(f"<start_of_turn>user\n{msg.content}<end_of_turn>")
        elif msg.role == "assistant":
            prompt_parts.append(f"<start_of_turn>model\n{msg.content}<end_of_turn>")
    prompt_parts.append("<start_of_turn>model\n")
    prompt = "\n".join(prompt_parts)

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=request.max_tokens,
            temperature=max(request.temperature, 0.01),
            do_sample=request.temperature > 0,
        )
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    response_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

    return ChatResponse(choices=[
        Choice(message=Message(role="assistant", content=response_text))
    ])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8357)
PYEOF

ok "Created $MODEL_DIR/serve_27b.py"

# ── Write MedGemma 4B server script ─────────────────────────
if [ "$SKIP_4B" = false ]; then
cat > "$MODEL_DIR/serve_4b.py" << 'PYEOF'
"""MedGemma 4B IT — FastAPI model server (multimodal, radiology images)."""
import os, torch, logging, base64, io
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from transformers import AutoProcessor, AutoModelForImageTextToText
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medgemma-4b")

app = FastAPI(title="MedGemma 4B IT")

MODEL_ID = "google/medgemma-4b-it"
processor = None
model = None

class GenerateRequest(BaseModel):
    prompt: str
    image_base64: Optional[str] = None
    max_tokens: int = 1024

class GenerateResponse(BaseModel):
    text: str
    model: str = MODEL_ID

@app.on_event("startup")
async def load_model():
    global processor, model
    logger.info(f"Loading {MODEL_ID}...")
    token = os.environ.get("HF_TOKEN")
    processor = AutoProcessor.from_pretrained(MODEL_ID, token=token)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_ID, token=token,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    logger.info("Model loaded successfully")

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_ID, "loaded": model is not None}

@app.post("/generate")
async def generate(request: GenerateRequest):
    image = None
    if request.image_base64:
        img_bytes = base64.b64decode(request.image_base64)
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    if image:
        inputs = processor(text=request.prompt, images=image, return_tensors="pt").to(model.device)
    else:
        inputs = processor(text=request.prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=request.max_tokens)
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    response_text = processor.decode(new_tokens, skip_special_tokens=True)

    return GenerateResponse(text=response_text)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8358)
PYEOF
ok "Created $MODEL_DIR/serve_4b.py"
fi

# ── Pre-download models ──────────────────────────────────────
info "Pre-downloading MedGemma 27B (this may take 10-20 minutes on first run)..."
python3 -c "
from huggingface_hub import snapshot_download
import os
snapshot_download('google/medgemma-27b-text-it', token=os.environ['HF_TOKEN'])
print('MedGemma 27B downloaded.')
"
ok "MedGemma 27B downloaded"

if [ "$SKIP_4B" = false ]; then
    info "Pre-downloading MedGemma 4B..."
    python3 -c "
from huggingface_hub import snapshot_download
import os
snapshot_download('google/medgemma-4b-it', token=os.environ['HF_TOKEN'])
print('MedGemma 4B downloaded.')
"
    ok "MedGemma 4B downloaded"
fi

# ── Start model servers ──────────────────────────────────────
info "Starting MedGemma 27B server on port 8357..."
cd "$MODEL_DIR"
nohup python3 serve_27b.py > medgemma_27b.log 2>&1 &
PID_27B=$!
echo "$PID_27B" > "$MODEL_DIR/27b.pid"
ok "MedGemma 27B started (PID: $PID_27B, log: $MODEL_DIR/medgemma_27b.log)"

if [ "$SKIP_4B" = false ]; then
    info "Starting MedGemma 4B server on port 8358..."
    nohup python3 serve_4b.py > medgemma_4b.log 2>&1 &
    PID_4B=$!
    echo "$PID_4B" > "$MODEL_DIR/4b.pid"
    ok "MedGemma 4B started (PID: $PID_4B, log: $MODEL_DIR/medgemma_4b.log)"
fi

# ── Wait for models to load ──────────────────────────────────
info "Waiting for models to load (this takes a few minutes)..."
echo ""

MAX_WAIT=600  # 10 minutes
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8357/health > /dev/null 2>&1; then
        ok "MedGemma 27B is ready"
        break
    fi
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    echo -ne "\r  Waiting... ${ELAPSED}s / ${MAX_WAIT}s"
done
echo ""

if [ $ELAPSED -ge $MAX_WAIT ]; then
    warn "MedGemma 27B did not respond within ${MAX_WAIT}s."
    warn "Check log: tail -f $MODEL_DIR/medgemma_27b.log"
fi

if [ "$SKIP_4B" = false ]; then
    ELAPSED=0
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        if curl -sf http://localhost:8358/health > /dev/null 2>&1; then
            ok "MedGemma 4B is ready"
            break
        fi
        sleep 10
        ELAPSED=$((ELAPSED + 10))
        echo -ne "\r  Waiting... ${ELAPSED}s / ${MAX_WAIT}s"
    done
    echo ""
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  MedGemma Model Servers — Ready"
echo "=============================================="
echo ""
echo "  Infrastructure:  docker compose up -d"
echo "  MedGemma 27B:    http://localhost:8357/health"
if [ "$SKIP_4B" = false ]; then
echo "  MedGemma 4B:     http://localhost:8358/health"
fi
echo "  Application:     http://localhost:8000/health"
echo "  OpenSearch:      http://localhost:9200"
echo "  Dashboards:      http://localhost:5601"
echo ""
echo "  Logs:"
echo "    27B model:  tail -f $MODEL_DIR/medgemma_27b.log"
if [ "$SKIP_4B" = false ]; then
echo "    4B model:   tail -f $MODEL_DIR/medgemma_4b.log"
fi
echo "    API:        docker compose logs -f api"
echo "    Scheduler:  docker compose logs -f scheduler"
echo "    Worker:     docker compose logs -f worker"
echo ""
echo "  To stop model servers:"
echo "    bash stop_models.sh"
echo ""
