# RossBot

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

### Local setup
```bash
uv sync --all-groups            # install pinned deps (see pyproject.toml)
docker compose up -d            # Postgres(+TimescaleDB) + Redis
cp .env.example .env            # fill local values; never commit .env
uv run alembic upgrade head     # apply schema v0 + seed config
```

### Checks (Definition of Done)
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All dependency versions are web-verified (2026-06) and pinned exactly — see the
"Versions verified" table in [`PROGRESS.md`](PROGRESS.md).
