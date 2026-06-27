@echo off
echo Setting up RossBot dev environment...
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
echo.
echo Done. Now:
echo 1. Copy .env.example to .env
echo 2. Fill in your Supabase connection string
echo 3. Run: python scripts/run_migrations.py
echo 4. Run dev_start_api.bat in one terminal
echo 5. Run dev_start_dashboard.bat in another terminal
