"""Apply Alembic migrations against ROSSBOT_DATABASE_URL (local dev, no Docker).

Usage:
    python scripts/run_migrations.py

Loads .env (so ROSSBOT_DATABASE_URL / Supabase connection string is picked up), then runs
`alembic upgrade head`. db/migrations/env.py adds sslmode=require automatically for Supabase.
"""

from __future__ import annotations

import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

# Use sys.executable so alembic runs under the same Python/venv that launched this script.
# Avoids "alembic not found" on Windows when the executable isn't on PATH.
result = subprocess.run(  # noqa: S603
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    capture_output=False,
)
sys.exit(result.returncode)
