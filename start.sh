#!/usr/bin/env bash
# ============================================================================
# RossBot demo launcher (Git Bash / WSL / macOS / Linux).
# Starts the FastAPI backend (Alpaca paper trading loop runs in-process) and
# the Next.js dashboard. Ctrl+C stops both.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# Locate the venv python (.venv on Windows uses Scripts/, POSIX uses bin/).
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "[ERROR] .venv not found. Create it first:"
  echo "    python -m venv .venv && source .venv/Scripts/activate && pip install -r requirements.txt alpaca-py"
  exit 1
fi

echo "=== RossBot demo ==="
echo "Starting FastAPI backend (port 8000) — trading loop runs in-process..."
"$PY" -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

echo "Starting Next.js dashboard (port 3000)..."
( cd dashboard && npm run dev ) &
DASH_PID=$!

cleanup() {
  echo ""
  echo "Stopping..."
  kill "$API_PID" "$DASH_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo ""
echo "============================================================"
echo "  API:        http://localhost:8000"
echo "  API health: http://localhost:8000/health"
echo "  Watchlist:  http://localhost:8000/api/watchlist"
echo "  Dashboard:  http://localhost:3000"
echo "============================================================"
echo "(Ctrl+C to stop both.)"

wait
