# RossBot

## Local Development (No Docker)

### Prerequisites
- Python 3.11+ installed
- Node.js 18+ installed
- A free Supabase account at supabase.com (hosted PostgreSQL)
- A free Upstash account at upstash.com (hosted Redis — hot state / pub-sub)

### First-time setup
1. Clone the repo
2. Run `setup_dev.bat` (Windows) — sets up the Python virtual environment
3. Copy `.env.example` to `.env`
4. **Database (Supabase):** supabase.com → New Project → Settings → Database → copy the URI
   connection string. Paste it as `ROSSBOT_DATABASE_URL` in `.env`
   (prefix the host with `postgresql+psycopg://`; SSL `sslmode=require` is added automatically)
5. **Redis (Upstash):** upstash.com → create database → Connect → copy the TLS URL. Paste it as
   `ROSSBOT_REDIS_URL` in `.env` (format `rediss://default:<password>@<endpoint>.upstash.io:6379`)
6. Create the schema: `python scripts/run_migrations.py`
   → "Running upgrade … head" means all 12 tables were created in Supabase
7. **Harden Supabase:** open `db/supabase_setup.sql`, paste it into the Supabase SQL Editor and
   run it. This enables Row-Level Security + revokes the public Data API so your trading data
   isn't exposed. (The bot connects as `postgres` and bypasses RLS, so it keeps full access.)
8. Verify Redis: `python scripts/check_redis.py` → "Redis OK"

### Daily dev workflow
- Terminal 1: `dev_start_api.bat` → FastAPI at http://localhost:8000
- Terminal 2: `dev_start_dashboard.bat` → Dashboard at http://localhost:3000
- API docs: http://localhost:8000/docs

### Verify it works
- Open http://localhost:8000/health → should return `{"status": "ok", "service": "rossbot", "phase": 5}`
- Open http://localhost:8000/docs → should show all API routes

> The old Docker/`docker-compose` infra is archived under `_docker_archive/` (kept for future
> production use; not tracked in git). PostgreSQL now lives in Supabase via `ROSSBOT_DATABASE_URL`.

---

Automated US-equities day-trading bot replicating Ross Cameron's (DaytradeWarrior) strategy.
**Source of truth for all rules:** [`ROSSBOT_STRATEGY_SPEC.md`](ROSSBOT_STRATEGY_SPEC.md) (V2.0).
**Build plan:** [`ROSSBOT_PROJECT_PLAN.md`](ROSSBOT_PROJECT_PLAN.md). **Contract:** [`CLAUDE.md`](CLAUDE.md).

> Real money, real client. Risk gate before the money path ("brakes before engine").
> Money is `Decimal`/integer-cents, never `float`. On any uncertainty → do not trade.

## Phase 0 — Infrastructure & Adapters (current)

The spine: monorepo, schema, config service, vendor-agnostic adapter interfaces, CI.
**No strategy logic yet.**

### Layout
```
core/        # shared kernel: config service, Decimal money, UTC/ET time, JSON logging, clock-drift
adapters/    # vendor-agnostic ABCs (BrokerAdapter, MarketDataAdapter) + fail-closed provider stubs
db/          # SQLAlchemy models (12 tables), Alembic migrations, config seed (C1–C16)
api/         # FastAPI app (health only in Phase 0)
dashboard/   # Next.js (Phase 5 placeholder)
tests/       # pytest suite
```

### Local setup (uv — alternative to the no-Docker flow above)
```bash
uv sync --all-groups            # install pinned deps (see pyproject.toml)
cp .env.example .env            # fill local values (Supabase URL); never commit .env
uv run alembic upgrade head     # apply schema v0 + seed config (against Supabase)
```
> Database is hosted on Supabase (set `ROSSBOT_DATABASE_URL`); Redis is hosted on Upstash
> (set `ROSSBOT_REDIS_URL`). No local Postgres/Redis/Docker needed.

### Checks (Definition of Done)
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All dependency versions are web-verified (2026-06) and pinned exactly — see the
"Versions verified" table in [`PROGRESS.md`](PROGRESS.md).
