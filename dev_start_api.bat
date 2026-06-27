@echo off
echo Starting RossBot FastAPI backend...
call venv\Scripts\activate
uvicorn api.main:app --reload --port 8000
