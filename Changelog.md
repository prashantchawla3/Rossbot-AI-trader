# Changelog — RossBot

All notable changes per CLAUDE.md §11.4. Format: reverse-chronological, one entry per phase/change.

## [Phase 2] Strategy Engine (Signal Detection) — 2026-06-26

Entry AND-gate, label-agnostic pattern recognisers, conviction scorer, exit engine.
**Outputs signals only — nothing routes to the broker.** Phase 3 Risk Manager must exist before
any signal reaches the execution path ("brakes before engine"). 259 passing / 3 skipped.

### Added

- **`core/strategy/models.py`** — All Phase 2 DTOs: `PatternType` (9 patterns + NONE),
  `PATTERN_RANK` dict, `ExitReason`, `ScaleAction`, `PullbackContext`, `EntryGateResult`,
  `EntrySignal` (with `rr_ratio`/`risk_per_share` properties), `PositionSnapshot` (immutable;
  high-watermark updated by creating new snapshot), `ExitSignal`, `FailedPatternSignal`.
  All frozen Pydantic models. Money fields are `Decimal`; no float.

- **`core/strategy/entry_gate.py`** — Pure E1–E7 AND-gate:
  - E1 tier_b_pass; E2 1–3 red pullback; E3 candle-over-candle new high;
    E4 MACD positive (hard-block on None); E5 retrace ≤ RETRACE_MAX (C9);
    E6 L2 SUPPORT or ABSORB_BREAK (UNKNOWN/ICEBERG/SPOOF → fail-closed);
    E7 spread ∈ [SPREAD_MIN, SPREAD_MAX].
  - `find_pullback_context`: scans backward from bars[-2]; minimum 6 bars.
  - `ENTRY_TRIGGER` forced to `candle_close` unless `market_state = HOT` (spec C12).

- **`core/strategy/patterns.py`** — 9 label-agnostic pattern recognisers (spec §4A):
  - `is_micro_pullback` (R1), `is_abcd` (R2, P2≥P1 invariant), `is_bull_flag` (R3),
    `is_flat_top` (R3 variant), `is_gap_and_go` (R5), `is_vwap_break` (R6),
    `is_halt_resumption` (R7), `is_red_to_green` (R10), `is_reverse_split_squeeze` (R11).
  - `is_topping_candle`: upper shadow ≥ 2× body (or doji).
  - `is_failed_pattern`: universal §4A invalidation set — topping-tail confirmed by next candle
    new low, false-breakout-flush, candle-under-candle, below 9-EMA, below VWAP, MACD negative
    cross, retrace > 50%, light-volume breakout after spike (RKDA fixture).
  - `recognize_pattern`: returns highest-priority match (lowest PATTERN_RANK value).
  - **Bug fixed**: volume arithmetic was mixing Python `float` with `Decimal` → `TypeError`.
    All volume comparisons now use plain float/int; only prices/PnL use Decimal.

- **`core/strategy/conviction.py`** — Conviction scorer [0.25, 1.0]:
  pattern 30% + RVOL 25% + float 15% + attention 15% + spread 8% + retrace 7%.
  Bonuses: 9-EMA touch +0.05, VWAP reclaim +0.03. Clamped to [0.25, 1.0].

- **`core/strategy/exit_engine.py`** — P1–P8 in priority order (first match wins):
  P1 hard stop (mental/marketable-limit, U13); P2 breakout-or-bailout (+10¢/60s);
  P3 L2 reversal (SPOOF/ICEBERG); P4 topping tail **confirmed** by next candle new low;
  P5 scale into strength (HOD break or $0.50/$1.00 psych level) → PARTIAL_SCALE + move-to-BE;
  P6 first red close; P7 VWAP guard; P8 lost popularity. No native STOP ever (U13).

- **`core/strategy/engine.py`** — `StrategyEngine` + `SymbolState`:
  - 10s bars update indicators + `intraday_high` only; no signals generated.
  - 1m bars drive entry gate → pattern → conviction → `EntrySignal`.
  - When gate fails + pullback_ctx exists → `is_failed_pattern` → `FailedPatternSignal`.
  - `reset_session` clears all per-session state including position (U3 no-overnight).
  - `open_position`/`close_position`/`update_stop`/`set_halted_resume`/`set_market_rank`
    lifecycle callbacks called by the (future) Risk + Execution layers.

- **Config additions** (`core/config.py`): `PULLBACK_MAX_CANDLES` (3), `SURGE_MIN_CANDLES` (2),
  `PSYCH_LEVEL_STEP` (0.50), `PSYCH_LEVEL_TOLERANCE` (0.03), `FLAG_CONSOLIDATION_MAX` (0.25),
  `LIGHT_VOLUME_RATIO` (0.30), `VOLUME_SPIKE_LOOKBACK` (10).

- **Tests** (138 new; 259 passing + 3 Postgres skipped):
  - `tests/test_entry_gate.py` (30): E1–E7 pass + fail; MACD hard-block; spread=0.01 skip;
    find_pullback_context geometry; mid-candle gated to HOT.
  - `tests/test_patterns.py` (38): all 9 patterns; ABCD P2<P1 void; topping-tail confirmation
    (single candle alone = NOT a failure; needs next-candle confirmation); RKDA
    light-volume-after-spike; all `is_failed_pattern` conditions.
  - `tests/test_conviction.py` (18): clamp; pattern rank ordering; RVOL/float/attention/spread/
    retrace sensitivity; bonuses stack correctly.
  - `tests/test_exit_engine.py` (22): P1–P8 each fires + does not fire; priority ordering
    (P1 > P2 > P3…); P4 topping-tail requires next-candle confirmation; P5 PARTIAL_SCALE.
  - `tests/test_strategy_fixtures.py` (30): §12 regression fixtures — SLXN-style WIN generates
    `EntrySignal` (MACD pre-warmed 36 bars); RKDA loss (L2=UNKNOWN → E6 fails → no entry);
    GMBL loss (L2=ICEBERG → E6 fails → no entry); PALI loss (secondary-offering → tier_b=False →
    E1 fails → no entry); U3 reset clears position; 10s bars return no signals.

### Notes
- Signals land in `EntrySignal` / `ExitSignal` / `FailedPatternSignal` objects only.
  The `signals` DB table (`SignalRow`) is not yet written to by the engine — that write-path
  belongs in Phase 3 (Risk Manager) once the veto gate exists.
- MACD(12,26,9) requires 34 bars minimum before histogram is non-None. Integration tests
  pre-warm with 36 bars of rising price to ensure E4 passes in fixture tests.
- **`is_abcd`**: the actual H1 level is computed geometrically by `_find_abcd_structure`
  from the bar history — it does NOT use `ctx.surge_high`.

---

## [Phase 1] Data Layer (Scanner + Market Data) — 2026-06-26

Real-time/historical data plumbing: two-tier scanner, indicators, RVOL, float resolver, feed
integrity, vendor adapters. Pure strategy/data logic in `core/`; vendor wiring in `adapters/`.
Vendor APIs web-verified 2026-06 (Alpaca `alpaca-py` 0.43.4, Databento 0.80.0, SEC EDGAR
`data.sec.gov`). Indicators hand-implemented on `Decimal` — no numpy/pandas (lean + deterministic).

### Added
- **Indicators** (`core/indicators.py`): 9-EMA, session-VWAP, MACD(12/26/9) — each as a
  hand-computed `Decimal` batch fn + an incremental streaming state (batch/stream agree
  bit-for-bit). `macd_positive` E4 helper fails closed on un-seeded points. Float inputs rejected.
- **Bar builder** (`core/data/bars.py`): builds 10s/1m OHLCV from the tick tape with documented
  rules — **pre-market included**, **odd lots included**, UTC-epoch bucket alignment, complete-bar
  emission, out-of-order prints ignored. `MultiTimeframeBarBuilder` fans 10s+1m.
- **Feed integrity** (`core/data/feed_integrity.py`): SIP/consolidated guard
  (`require_consolidated_feed` rejects IEX-only/OTC/delayed) + `StalenessDetector` (per-key gap
  detector; unseen key = stale = do-not-trade, fail-safe).
- **RVOL engine** (`core/scanner/rvol.py`): rolling 50-day baseline ratio + intraday projection;
  low-confidence flag below `RVOL_MIN_HISTORY_DAYS` — low/unknown confidence cannot pass Pillar 3.
- **Float resolver** (`core/scanner/float_resolver.py`): reconciles vendor free-float + EDGAR
  shares-outstanding into a value + confidence (HIGH/MEDIUM/LOW/UNKNOWN). Disagreement, or
  float>shares-out, ⇒ LOW; LOW/UNKNOWN must not pass Pillar 2 (bad float never silently passes).
- **Two-tier scanner** (`core/scanner/`): Tier A wide net (surveillance) → Tier B Five-Pillars
  trade gate (P1–P5, all inclusive thresholds from config); attention ranking (PRIME/WATCH/IGNORE).
  Tier A tolerates unknown float; only Tier B is tradeable (U1). Sub-scanners (§9): top-gainers,
  low-float-top-gainer, HOD-momentum, running-up, halt, reverse-split/IPO, continuation.
- **Vendor adapters** (`adapters/`, optional `rossbot[vendors]`, import-guarded): `AlpacaMarketDataAdapter`
  (bars/quotes/tape/news via SIP; depth delegated to Databento), `DatabentoDepthTapeAdapter`
  (MBP-10 depth + trades tape over XNAS.ITCH), `EdgarClient` (stdlib `urllib`; ticker→CIK,
  latest shares-outstanding; injectable fetcher → offline-testable).
- **Config** (`core/config.py` + Alembic `0002`): Tier-A net thresholds, attention ranks, volume
  sweet-spot, sub-scan thresholds, RVOL baseline/min-history, float-disagree tolerance,
  `REQUIRE_SIP`, `FEED_STALENESS_SECONDS`. Migration `0002` re-seeds (idempotent).
- **Tests** (84 new; 121 passing + 3 Postgres-integration skipped): indicator fixtures (EMA/VWAP/
  MACD hand-verified), bar build (odd-lot/pre-market/alignment/out-of-order), SIP-vs-IEX guard,
  staleness trip, RVOL low-confidence, float low-confidence flagging, EDGAR parsing (offline),
  scanner boundary cases at every pillar/Tier-A threshold, sub-scanners.

### Notes / open items
- `pyproject.toml`: added optional `vendors` group (alpaca-py 0.43.4, databento 0.80.0) + mypy
  `ignore_missing_imports` for the uninstalled SDKs; no numpy/pandas added.
- **NEEDS-VERIFY before live**: exact Databento DBN `Mbp10Msg.levels` layout + fixed-point price
  scale + Live-iteration API (flagged in `adapters/databento.py`); Alpaca per-feed pre-market
  coverage; vendor free-float field names. Schemas/clients/auth/versions are verified.
- Local validation: Ruff + mypy + pytest (121 passed, 3 integration skipped) green on the 3.12 venv.

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
