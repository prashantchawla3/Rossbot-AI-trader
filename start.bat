@echo off
REM ===========================================================================
REM RossBot launcher (Windows)
REM
REM TWO WAYS TO RUN THE BOT:
REM
REM  Option A — Terminal mode (see the bot work right here, no browser needed):
REM    .venv\Scripts\python.exe scripts\run_bot.py
REM    .venv\Scripts\python.exe scripts\run_bot.py --no-trade   (signals only)
REM
REM  Option B — Full dashboard mode (API + Next.js UI at localhost:3000):
REM    Just run this script — it opens two windows below.
REM
REM Requires:
REM   .env with ALPACA_API_KEY and ALPACA_SECRET_KEY
REM   .venv with deps:  pip install -e ".[vendors]"
REM   dashboard\node_modules:  cd dashboard && npm install
REM ===========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [ERROR] .venv not found. Run this first:
  echo   python -m venv .venv
  echo   .venv\Scripts\activate
  echo   pip install -e ".[vendors]"
  echo.
  pause
  exit /b 1
)

echo.
echo ===========================================================================
echo   RossBot  -  Paper Trading Bot
echo ===========================================================================
echo.
echo   Option A: watch the bot in this terminal (no browser needed)
echo   ^> .venv\Scripts\python.exe scripts\run_bot.py
echo.
echo   Option B: full dashboard (launching now...)
echo ===========================================================================
echo.

echo Starting RossBot API on http://localhost:8000 ...
start "RossBot API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000 2>&1"

echo Starting RossBot Dashboard on http://localhost:3000 ...
start "RossBot Dashboard" cmd /k "cd dashboard && npm run dev"

echo.
echo ===========================================================================
echo   API:              http://localhost:8000
echo   API health:       http://localhost:8000/health
echo   Watchlist (JSON): http://localhost:8000/api/watchlist
echo   Dashboard UI:     http://localhost:3000
echo ===========================================================================
echo.
echo   The trading engine is now running inside the API window.
echo   Entry window: 07:00 - 11:00 ET on weekdays (spec ^SS7).
echo   Outside those hours the bot scans but does not enter positions.
echo.
echo   To stop: close both terminal windows, or press Ctrl+C in each.
echo.
echo   TIP: for a simpler view run the terminal runner instead:
echo        .venv\Scripts\python.exe scripts\run_bot.py
echo ===========================================================================
endlocal
