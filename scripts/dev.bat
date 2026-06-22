@echo off
REM Run Reeler on Windows: FastAPI backend (:8000) + Vite frontend (:5173).
REM Double-click this file, or run it from a terminal in the repo.
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

if not exist .venv (
  echo Creating Python venv and installing dependencies...
  py -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\pip install -q -r backend\requirements.txt
)

REM Load .env (KEY=VALUE lines; eol=# skips comments) into this environment.
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" set "%%a=%%b"
  )
)

echo Starting backend on http://localhost:8000 ...
start "Reeler API" cmd /k ".venv\Scripts\uvicorn --app-dir backend app.main:app --reload --port 8000"

echo Starting frontend on http://localhost:5173 ...
cd frontend
if not exist node_modules ( call npm install )
call npm run dev
