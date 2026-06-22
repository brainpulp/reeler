@echo off
REM Run Reeler on Windows: FastAPI backend (:8000) + Vite frontend (:5173).
REM Double-click this file, or run it from a terminal in the repo.
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

if not exist .venv (
  echo Creating Python venv...
  REM Prefer a stable interpreter; very new Pythons (e.g. 3.14) may lack wheels.
  py -3.13 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -m venv .venv 2>nul || python -m venv .venv
  echo Installing dependencies...
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install --no-cache-dir -r backend\requirements.txt
)

REM Load .env (KEY=VALUE lines; eol=# skips comments) into this environment.
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" set "%%a=%%b"
  )
)

echo Starting backend on http://localhost:8000 ...
start "Reeler API" cmd /k ".venv\Scripts\python -m uvicorn --app-dir backend app.main:app --reload --port 8000"

echo Starting frontend on http://localhost:5173 ...
cd frontend
if not exist node_modules ( call npm install )
call npm run dev
