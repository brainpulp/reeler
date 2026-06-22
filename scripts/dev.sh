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
# Reeler needs Python 3.11+. Pick the newest available interpreter.
PYBIN=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys; print("%d%d" % sys.version_info[:2])')"
    if [ "$ver" -ge 311 ]; then PYBIN="$cand"; break; fi
  fi
done
if [ -z "$PYBIN" ]; then
  echo "❌ Need Python 3.11+. On macOS: brew install python@3.11" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating venv with $PYBIN ($("$PYBIN" --version))"
  "$PYBIN" -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
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
