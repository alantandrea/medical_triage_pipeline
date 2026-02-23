#!/usr/bin/env bash
###############################################################################
# Stop MedGemma model servers started by setup_models.sh
###############################################################################

MODEL_DIR="$HOME/medgemma-servers"

echo "Stopping MedGemma model servers..."

if [ -f "$MODEL_DIR/27b.pid" ]; then
    PID=$(cat "$MODEL_DIR/27b.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "  Stopped MedGemma 27B (PID: $PID)"
    else
        echo "  MedGemma 27B was not running (PID: $PID)"
    fi
    rm -f "$MODEL_DIR/27b.pid"
fi

if [ -f "$MODEL_DIR/4b.pid" ]; then
    PID=$(cat "$MODEL_DIR/4b.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "  Stopped MedGemma 4B (PID: $PID)"
    else
        echo "  MedGemma 4B was not running (PID: $PID)"
    fi
    rm -f "$MODEL_DIR/4b.pid"
fi

echo "Done."
