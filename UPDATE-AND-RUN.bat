@echo off
REM ============================================================
REM  Reeler - double-click to UPDATE and RUN.
REM  Every launch: pulls the latest code, stops any old windows,
REM  then starts the backend (:8000) + frontend (:5173) and opens
REM  the app. No git, no terminals, no restart-guessing.
REM
REM  If your folders ever change, edit only the two PATH lines
REM  marked [cookie] and [data] below.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- [cookie] your exported Instagram cookies.txt ---
if not defined REELER_IG_COOKIE_FILE set "REELER_IG_COOKIE_FILE=F:\downloads\www.instagram.com_cookies.txt"
REM --- [data] where the videos + reeler.db live ---
if not defined REELER_DATA_DIR set "REELER_DATA_DIR=F:\Users\mxgld\reeler\data"

REM Optional .env overrides (KEY=VALUE lines; # comments skipped).
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" set "%%a=%%b"
  )
)

REM Guard against the classic empty-grid bug: a wrong/missing data
REM folder makes the app scan 0 files and look broken. Stop early.
if not exist "%REELER_DATA_DIR%" (
  echo [!] Data folder not found: %REELER_DATA_DIR%
  echo     Plug in the F: drive or fix the [data] line above, then rerun.
  pause
  exit /b 1
)

echo Stopping any old Reeler windows...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:":8000 " ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:":5173 " ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1

echo Updating to the latest code...
git fetch origin
git checkout claude/vigilant-tesla-16tdba 2>nul
git pull --ff-only

echo Starting backend on http://localhost:8000 ...
start "Reeler API" cmd /k ".venv\Scripts\python -m uvicorn --app-dir backend app.main:app --reload --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "Reeler UI" cmd /k "cd /d %~dp0frontend && npm run dev"

REM Give Vite a moment to boot, then open the app (proxy port, not :8000).
timeout /t 6 >nul
start "" http://localhost:5173
exit /b 0
