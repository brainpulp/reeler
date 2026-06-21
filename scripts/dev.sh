#!/usr/bin/env bash
# Run Reeler in development: FastAPI backend + Vite frontend with hot reload.
# Backend serves the API on :8000, Vite serves the UI on :5173 and proxies /api.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load .env if present so the backend picks up your Instagram cookie config.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# --- backend ---
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r backend/requirements.txt
fi
( cd backend && "$ROOT/.venv/bin/uvicorn" app.main:app --reload --port 8000 ) &
BACK=$!

# --- frontend ---
( cd frontend && [ -d node_modules ] || npm install; npm run dev ) &
FRONT=$!

trap 'kill $BACK $FRONT 2>/dev/null' EXIT
echo "Reeler: API http://localhost:8000  UI http://localhost:5173"
wait
