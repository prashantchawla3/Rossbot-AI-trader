# Changelog — RossBot

All notable changes per CLAUDE.md §11.4. Format: reverse-chronological, one entry per phase/change.

## [Phase 0] Infrastructure & Adapters — 2026-06-26

The spine. Monorepo, schema, config service, vendor-agnostic adapter interfaces, CI.
**No strategy logic** (per plan). All dependency versions web-verified 2026-06 and pinned exactly.

### Added
- **Monorepo skeleton**: `core/` (kernel), `adapters/` (vendor-agnostic ABCs), `db/`
  (SQLAlchemy models + Alembic), `api/` (FastAPI health), `dashboard/` (Phase 5 placeholder),
  `tests/`.
- **Dependency manifest** (`pyproject.toml`, uv) — pinned: Python 3.13, FastAPI 0.138.1,
  Pydantic 2.13.4, pydantic-settings 2.14.2, SQLAlchemy 2.0.51, Alembic 1.18.5,
  psycopg 3.3.4, redis 8.0.1, structlog 26.1.0, ntplib 0.4.0; dev: Ruff 0.15.20, mypy 2.1.0,
  pytest 9.1.1.
- **docker-compose.yml**: TimescaleDB `pg17.10-ts2.28.1` + Redis `8.0.1`; `.env.example`
  (no secrets; strategy conflicts live in DB, not env).
- **Postgres schema v0** (Alembic `0001`): 12 tables (`symbols`, `bars`, `quotes`,
  `depth_snapshots`, `tape_prints`, `signals`, `orders`, `fills`, `positions`, `ledger`,
  `risk_events`, `config`). NUMERIC money everywhere; append-only triggers on `ledger` &
  `risk_events`; TimescaleDB hypertables on the time-series tables (guarded — skipped on plain
  Postgres). `orders.order_type` CHECK-constrained to limit/marketable_limit only (U7/U13 by
  construction).
- **Config service**: `config` table + typed `ConfigService` loader seeded with cautious
  C1–C16 defaults + operational guardrail keys (Five Pillars, spread band, offsets, U-rule
  thresholds, U6 sim gate, fail-safe market-state).
- **Adapter ABCs**: `BrokerAdapter` (submit_marketable_limit, partial_sell,
  cancel_all_flatten, account_state, get_halt_status — **no native STOP method**) and
  `MarketDataAdapter` (subscribe_depth/tape/bars, get_quote, news_stream), with frozen
  Pydantic DTOs (Money-typed).
- **Fail-closed provider stubs** (Rule C): `CatalystProvider`→UNVERIFIED,
  `L2SignalProvider`→UNKNOWN, `MarketStateProvider`→COLD.
- **Cross-cutting kernel**: Decimal money (`core.money`, floats rejected) + SQLAlchemy
  `Money` column; UTC/ET time helpers (DST-correct) + session classifier; structlog JSON
  logging; NTP clock-drift guard (fail-closed).
- **Tests** (37 passing + 3 Postgres integration): float-into-ledger rejected at app & storage
  boundaries; config loader returns seeded C1–C16; adapter ABCs not instantiable; stubs fail
  closed; OrderType has no stop/market; DST/session; clock-drift fail-safe; Alembic up/down +
  append-only triggers (integration).
- **CI** (`.github/workflows/ci.yml`): Ruff + mypy + pytest on PR, with a TimescaleDB service
  so integration tests run.

### Notes / open items
- Local validation: Ruff, mypy, and pytest (37 passed) green on a 3.12 venv; Alembic
  upgrade/downgrade validated end-to-end on SQLite. The Postgres-only triggers/hypertables run
  in CI (local Docker engine was unavailable this session).
- OPEN client decisions still blocking later phases: (1) data/broker vendor; (2) account
  type/equity. No vendor is wired — adapters are interface-only.
