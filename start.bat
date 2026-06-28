@echo off
REM ===========================================================================
REM RossBot demo launcher (Windows). Starts the FastAPI backend (which runs the
REM Alpaca paper trading loop in-process) and the Next.js dashboard.
REM Requires: .venv (python deps) + dashboard\node_modules (npm install).
REM ===========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Create it and install deps:
  echo     python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt alpaca-py
  exit /b 1
)

echo Starting RossBot API on http://localhost:8000 ...
start "RossBot API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000"

echo Starting RossBot dashboard on http://localhost:3000 ...
start "RossBot Dashboard" cmd /k "cd dashboard && npm run dev"

echo.
echo ===========================================================================
echo   API:        http://localhost:8000
echo   API health: http://localhost:8000/health
echo   Watchlist:  http://localhost:8000/api/watchlist
echo   Dashboard:  http://localhost:3000
echo ===========================================================================
echo (Two new terminal windows opened. Close them to stop.)
endlocal
