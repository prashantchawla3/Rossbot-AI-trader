# Changelog — RossBot

All notable changes per CLAUDE.md §11.4. Format: reverse-chronological, one entry per phase/change.

## [Phase 7] Catalyst Detection — 2026-06-26

Replaced `StubCatalystProvider` (always UNVERIFIED) with `NLPCatalystProvider` — a real
layered classifier. Defence-in-depth: reaction-proof gate → SEC EDGAR dilution check →
Benzinga headline fetch → keyword SKIP scan → Claude Haiku 4.5 LLM tagging.
Hard-blocks PALI (secondary offering) and PTPI (buyout). Biases to UNVERIFIED/SKIP on ambiguity.

### Added (Python — catalyst detection)

- **`adapters/catalyst/__init__.py`** — Package marker; re-exports `CatalystResult`,
  `CatalystTag`, `NewsItem`, `NLPCatalystProvider`.

- **`adapters/catalyst/models.py`** — `CatalystTag` StrEnum (12 accepted + 7 SKIP + unknown);
  `ACCEPTED_TAGS`/`SKIP_TAGS` frozensets; `NewsItem` frozen dataclass (headline, body, url,
  source, published_at); `CatalystResult` frozen dataclass (tag, confidence, reasoning, source).

- **`adapters/catalyst/keyword_filter.py`** — `scan_for_skip(text)` instant substring SKIP
  detector. No API call. Covers: buyout/acquisition (SKIP_1), secondary/shelf offering (SKIP_3),
  pump/newsletter (SKIP_4), 5-cent tick pilot (SKIP_6). Bias: conservative — only clear-signal
  phrases matched.

- **`adapters/catalyst/sec_filing.py`** — `SecFilingClient` checks EDGAR submissions API
  (free, no key: `data.sec.gov/submissions/CIK###.json`) for recent S-1/S-3/424B* filings
  (dilution → SKIP) and 13D/13G (accepted catalyst). Reuses `parse_ticker_map` from
  `adapters/edgar.py`. CIK map cached across calls. Fail-safe: network error → False (no
  false-SKIP).

- **`adapters/catalyst/benzinga_feed.py`** — `BenzingaNewsClient` fetches recent headlines
  via `https://api.benzinga.com/api/v2/news`. Auth via `BENZINGA_API_KEY` env var (secret —
  never stored in DB). `updatedSince` delta polling. Falls back to [] on any error (fail-safe).
  Network I/O injectable for offline tests.

- **`adapters/catalyst/llm_classifier.py`** — `LLMCatalystClassifier` zero-shot structured
  JSON output via Claude Haiku 4.5 (`claude-haiku-4-5-20251001`; $1/$5 per MTok I/O,
  ≈$0.001/call verified 2026-06-26). Injected `client` param for offline tests. Falls back to
  `CatalystResult(UNKNOWN, 0)` on missing key, API error, or malformed JSON. Strips markdown
  fences from response.

- **`adapters/catalyst/provider.py`** — `NLPCatalystProvider` orchestrates all 5 layers.
  Accepts optional `rvol` / `roc_pct` kwargs for the reaction-proof gate (spec §13.1
  REAL_CATALYST ≥10% + ≥5×). All sub-components injectable. Async with `asyncio.to_thread`
  for sync I/O (urllib / Anthropic SDK).

- **`core/config.py`** — +5 Phase 7 config keys: `CATALYST_LLM_ENABLED` (true),
  `CATALYST_LLM_MODEL` ("claude-haiku-4-5-20251001"), `CATALYST_CONFIDENCE_THRESHOLD` (0.70),
  `CATALYST_FILING_LOOKBACK_DAYS` (30), `CATALYST_MAX_HEADLINES` (5).

### Modified

- **`adapters/providers.py`** — `CatalystProvider.classify` extended with keyword-only
  `rvol: Decimal | None = None` and `roc_pct: Decimal | None = None` args (backward-compatible;
  existing callers unaffected). Added `from decimal import Decimal` import.

- **`adapters/stubs.py`** — `StubCatalystProvider.classify` updated to accept new kwargs
  (still returns UNVERIFIED — Rule C unchanged).

### Tests (66 new, all passing)

- `tests/test_catalyst_keyword.py` — 23 tests: parametrized SKIP phrase hits for
  buyout/secondary/pump/5c-tick; parametrized no-hit for accepted catalysts; case-insensitive;
  first-match determinism.
- `tests/test_catalyst_sec_filing.py` — 13 tests: `_has_recent_filing` unit tests (S-3/424B3
  detect, old filing excluded, 8-K excluded, empty, bad JSON); `SecFilingClient` integration
  tests (PALI dilution, no filing, unknown ticker, network error, stake filing, UA validation,
  CIK map caching).
- `tests/test_catalyst_llm.py` — 13 tests: PTPI/PALI SKIP classification; FDA/earnings VERIFIED;
  low confidence preserved; UNKNOWN for ambiguous; error paths (no key, no headlines, API error,
  malformed JSON, unknown tag string, markdown fences).
- `tests/test_catalyst_provider.py` — 17 tests: PALI SKIP via SEC/keyword/LLM; PTPI SKIP via
  keyword/LLM; FDA VERIFIED with and without reaction proof; reaction gate low rvol/roc → UNVERIFIED;
  no headlines → UNVERIFIED; low confidence → UNVERIFIED; LLM disabled → UNVERIFIED; stub still
  fails closed; stub accepts new kwargs.

### Env vars required for live operation (never in DB)

- `BENZINGA_API_KEY` — Benzinga Pro REST API token
- `ANTHROPIC_API_KEY` — Claude API key (Haiku 4.5)

## [Phase 6] Live Trading — 2026-06-26

Hardened live broker path. Real money gate: U6 + readiness checklist + client sign-off. Staged
capital ramp (MICRO → STARTER → FULL). Reconciliation every 30 s. Idempotent orders.
Disconnect → flatten-or-freeze. Mental-stop monitor fires marketable-limit (never native STOP, U13).

### Added (Python — live trading layer)

- **`adapters/alpaca_broker.py`** — `AlpacaBrokerAdapter` implementing `BrokerAdapter` ABC.
  All Alpaca SDK imports lazy (optional vendor dep). `submit_marketable_limit`: limit @ ask+offset,
  TIF=IOC for RTH / TIF=DAY+extended_hours=True for PREMARKET/AFTERHOURS. Idempotent on 422 duplicate
  `client_order_id` (fetches existing order via `get_order_by_id` instead of double-fill). `partial_sell`:
  limit @ bid (U13 mental-stop exit). `cancel_all_flatten`: Alpaca `close_all_positions(cancel_orders=True)`
  (market order — emergency kill-switch exception to U7). `get_halt_status`: via `get_asset()` — NOTE:
  not intraday-accurate; Databento halt feed required for LULD detection (Phase 8). `get_broker_positions()`:
  `{symbol: qty}` dict for reconciliation. Fail-closed on all errors.

- **`core/config.py`** — +10 Phase 6 config keys (all in `DEFAULTS`): `LIVE_POLL_MS` (100 ms),
  `RECONCILE_INTERVAL_S` (30 s), `RECONNECT_MAX_ATTEMPTS` (3), `RECONNECT_DELAY_S` (5 s),
  `CAPITAL_RAMP_TIER` ("MICRO"), `CAPITAL_RAMP_MICRO_SHARES` (100), `CAPITAL_RAMP_STARTER_SHARES`
  (2000), `READINESS_MIN_BUYING_POWER` ($5,000), `READINESS_MIN_EQUITY` ($25,000), `CLOCK_DRIFT_MAX_MS`
  (500 ms).

- **`core/live/__init__.py`** — Package marker; re-exports `CapitalRamp`, `CapitalTier`, `LiveSession`,
  `ReadinessChecker`, `ReadinessItem`, `ReadinessResult`, `ReconcileResult`, `reconcile_positions`.

- **`core/live/models.py`** — Frozen dataclasses: `CapitalTier` (MICRO/STARTER/FULL StrEnum),
  `ReadinessItem` (name, passed, detail), `ReadinessResult` (items tuple, `all_passed` computed,
  `failed_names()`, `summary()`), `ReconcileResult` (matched, broker_only, internal_only, qty_mismatch
  as frozensets; `clean` property; `summary()`).

- **`core/live/reconcile.py`** — Pure function `reconcile_positions(broker: dict[str, int],
  internal: dict[str, int]) → ReconcileResult`. No side effects. Four categories: matched (symbol+qty
  agree), broker_only (ghost — alert), internal_only (orphan — auto-clear), qty_mismatch.

- **`core/live/capital_ramp.py`** — `CapitalRamp` class. Reads `CAPITAL_RAMP_TIER` at init
  (fail-safe to MICRO on unknown value). `apply(approved_shares)` clamps by tier max. `max_for_tier()`
  returns None for FULL (no cap). Config is read once at startup; never modified mid-session (U11).

- **`core/live/readiness.py`** — `ReadinessChecker.check_all()` runs 8 independent checks (no
  fail-fast — always returns full picture). Checks: (1) LIVE_ENABLED, (2) U6_GATE via SimulatorGate,
  (3) ACCOUNT_TYPE not UNKNOWN, (4) BUYING_POWER ≥ READINESS_MIN_BUYING_POWER, (5) PDT_EQUITY advisory
  (warns if margin <$25k, never blocks), (6) CAPITAL_TIER valid CapitalTier value, (7) CLOCK_DRIFT via
  ntplib (asyncio.to_thread), (8) DATA_FEED SPY quote probe within 10 s timeout.

- **`core/live/session.py`** — `LiveSession` — hardened PaperSession for real capital.
  `run()`: U6 hard gate + LIVE_ENABLED check before spawning any tasks; raises RuntimeError if not
  satisfied. Five concurrent async tasks: `_bar_loop` (strategy signals), `_mental_stop_loop`
  (100 ms poll, fires `partial_sell` on breach — U13), `_eod_flatten_loop` (10 s poll, flattens at
  EOD — U3), `_reconcile_loop` (30 s interval, removes orphans, logs ghosts + qty mismatches),
  `_feed_watchdog_loop` (sets `_frozen=True` on staleness, calls `_handle_disconnect`).
  `_handle_entry()`: risk.evaluate() → CapitalRamp.apply() → submit_marketable_limit.
  `_handle_disconnect()`: retries cancel_all_flatten up to max_attempts; if broker reachable, clears
  `_open`; if unreachable, stays frozen with CRITICAL log.

- **`RUNBOOK.md`** — Live trading runbook and incident playbook: pre-market readiness procedure
  (8-check table), capital ramp promotion guide, daily session procedure (07:00–EOD), order routing
  rules table, 7-scenario incident playbook (readiness fail, reconcile discrepancy, feed staleness,
  daily halt, kill-switch, duplicate fill, overnight hold), config key reference, monitoring endpoint
  guide, client sign-off template, open items gating real capital.

### Added (Python — tests, 63 new)

- **`tests/test_reconcile.py`** — 11 tests: all-matched, broker-only, internal-only, qty-mismatch,
  mixed discrepancy classes, empty-both, broker-empty, internal-empty, summary strings.

- **`tests/test_capital_ramp.py`** — 13 tests: tier property, MICRO/STARTER/FULL apply() caps,
  no-inflate below cap, zero passthrough, max_for_tier (None for FULL), apply() never exceeds approved.

- **`tests/test_readiness.py`** — 12 tests: all-pass happy path, each of the 8 checks failing
  independently, no-fail-fast (all 8 always run regardless of failures), ReadinessResult model.

- **`tests/test_live_adapter.py`** — 19 tests: AlpacaBrokerAdapter with mocked SDK;
  submit_marketable_limit (RTH IOC / pre-market DAY+extended); idempotency on 422 duplicate → fetch
  existing order; partial_sell limit @ bid; cancel_all_flatten calls close_all_positions; account state;
  get_broker_positions; halt status; fail-closed on errors.

- **`tests/test_live_session.py`** — 8 tests: U6 gate blocks run(), LIVE_ENABLED=false blocks,
  clean startup/stop, mental-stop fires partial_sell (not native STOP), reconcile removes orphan,
  disconnect+reachable → cancel_all_flatten called + _open cleared, disconnect+unreachable → _open
  preserved + stays frozen, EOD flatten clears _open.

### Broker / vendor decisions recorded

- **Primary broker:** Alpaca (alpaca-py 0.43.4). Paper sandbox + production share same SDK.
  No local Gateway process required (unlike IBKR). Production keys not yet issued.
- **Data:** Alpaca Algo Trader Plus subscription required (SIP). IEX-only (Basic plan) insufficient
  for live scanning (`REQUIRE_SIP=true`).
- **Halt detection gap:** `get_halt_status` via `get_asset()` does NOT detect intraday LULD halts.
  Databento/Polygon halt feed required — flagged as Phase 8 dependency.
- **IBKR (ib_async) evaluated but not selected:** Gateway-based, requires local process; more complex
  auth. Alpaca preferred for initial live. IB adapter can be added later via `BrokerAdapter` ABC.

---

## [Phase 5] Dashboard & Monitoring — 2026-06-26

Live read-only dashboard, FastAPI WebSocket push, kill-switch + pause controls, alerting, health
monitors, post-session journal. U11 enforced — zero parameter editing mid-session. Minimalist
monochrome design system (pure gray, zero hardcoded hex outside token file).

### Added (Python — FastAPI layer)

- **`api/auth.py`** — `require_api_key` dependency; reads `DASHBOARD_API_KEY` env var; raises 403 on
  wrong key, 503 when key is not configured.

- **`api/schemas/__init__.py`** — Package marker.

- **`api/schemas/dashboard.py`** — All Pydantic v2 frozen response models: `OpenPosition`,
  `RiskStateOut`, `WatchlistEntry`, `SignalEvent`, `RiskEventOut`, `FeedHealth`, `HealthOut`,
  `JournalEntry`, `SessionJournal`, `DashboardStateOut`, `WsMessage`, `ControlResult`.

- **`api/services/__init__.py`** — Package marker.

- **`api/services/ws_manager.py`** — `ConnectionManager`; `asyncio.Lock`-protected connection list;
  `broadcast_json` removes dead sockets; `connection_count` property.

- **`api/services/state_service.py`** — `StateService`; in-memory ring buffers (signals 200,
  risk_events 500 via `deque(maxlen=…)`); `register_risk_manager()`, `register_broker_cancel()`,
  `halt_session()`, `pause()`, `resume()`, `get_state()`, `set_broadcast_hook()`.

- **`api/services/alert_service.py`** — `AlertService`; `AlertSeverity` StrEnum (INFO/WARN/CRITICAL);
  Slack via `urllib.request`, email via `smtplib`, both in `ThreadPoolExecutor` (never blocks event
  loop); `async fire()` best-effort, never raises.

- **`api/services/health_service.py`** — `HealthService`; `record_tick()`, `declare_feed()`,
  `record_order_ack()`, `set_ws_clients()`; `refresh_clock_drift()` via ntplib in executor;
  `build_health_snapshot()` → `HealthOut`; `FEED_STALE_SECONDS` env var (default 30s).

- **`api/routers/__init__.py`** — Package marker.

- **`api/routers/dashboard.py`** — Read-only GET endpoints: `/api/state`, `/api/watchlist`,
  `/api/positions`, `/api/signals?limit=`, `/api/risk-events?limit=`, `/api/journal`.

- **`api/routers/controls.py`** — U11-compliant POST-only controls (`require_api_key` dep on all):
  `POST /controls/kill-switch`, `POST /controls/pause`, `POST /controls/resume`. Zero PATCH/PUT/DELETE.

- **`api/routers/health.py`** — `GET /health/` (HealthOut), `GET /health/ready` (200 or 503).

- **`api/main.py`** — Rewritten with `@asynccontextmanager lifespan`; instantiates all services;
  wires `ws_manager.broadcast_json` as broadcast hook; CORSMiddleware GET+POST only; WebSocket
  `/ws/live` (full state on connect, ping/pong loop); background `_health_loop` task.

### Added (Python — tests)

- **`tests/test_dashboard_api.py`** — Phase 5 acceptance tests: kill-switch invokes broker cancel;
  no PATCH/PUT/DELETE routes; WebSocket sends initial `state_update`; only 3 POST routes exist
  (no param mutation).

- **`tests/test_alert_service.py`** — Unit tests: no-channels case, Slack webhook called with correct
  URL, email dispatched via smtplib, severity injected into message, channel failure does not raise.

- **`tests/test_ws_manager.py`** — Unit tests: connect appends, disconnect removes, broadcast reaches
  all, dead connection (OSError) removed from pool.

- **`tests/test_health_service.py`** — Unit tests: stale feed detection, live feed, `all_healthy`
  false when stale, order ack latency recording, clock drift via ntplib mock.

### Added (TypeScript — Next.js dashboard)

- **`dashboard/package.json`** — Next.js 16.2, React 19.2, lightweight-charts v5, lucide-react
  0.475, geist 1.3, Tailwind CSS v4 / @tailwindcss/postcss v4.3, TypeScript 5.7.

- **`dashboard/next.config.ts`** — `reactStrictMode: true`; Turbopack default (Next 16).

- **`dashboard/postcss.config.mjs`** — `@tailwindcss/postcss` only.

- **`dashboard/tsconfig.json`** — Strict, `moduleResolution: "bundler"`, `@/*` path alias.

- **`dashboard/app/globals.css`** — Full Minimalist design system: brand-50–900 gray scale,
  background ramp, semantic role tokens (light + dark), `@theme inline` block wiring all CSS vars
  to Tailwind utilities, full component CSS class library (`.card`, `.btn`, `.badge`, `.metric-card`,
  `.nav-item`, `.table`, `.sidebar`, `.progress`, `.list`, etc.). Zero hardcoded hex outside `:root`
  primitive definition.

- **`dashboard/app/layout.tsx`** — Root layout; loads Geist (sans), Geist Mono, DM Serif Display via
  `next/font`; sets `<html>` class vars.

- **`dashboard/app/page.tsx`** — `redirect('/overview')`.

- **`dashboard/app/(dashboard)/layout.tsx`** — Wraps children in `DashboardProvider` + `Sidebar`.

- **`dashboard/app/(dashboard)/overview/page.tsx`** — Day P&L metrics grid, PnLChart
  (lightweight-charts v5), open positions, signal feed, kill-switch + badge.

- **`dashboard/app/(dashboard)/watchlist/page.tsx`** — Tier B (Five Pillars) + Tier A tables.

- **`dashboard/app/(dashboard)/signals/page.tsx`** — Full signal buffer (last 200).

- **`dashboard/app/(dashboard)/risk-events/page.tsx`** — Risk event log + CRITICAL/WARN counts.

- **`dashboard/app/(dashboard)/journal/page.tsx`** — Post-session journal: all trades, total P&L,
  win rate, max drawdown, spec refs per trade.

- **`dashboard/app/(dashboard)/health/page.tsx`** — Feed liveness, clock drift, order ack latency,
  WS client count.

- **`dashboard/components/Sidebar.tsx`** — Navigation with live/halted status dot.

- **`dashboard/components/Badge.tsx`** — Semantic badge variants (default/live/warn/success).

- **`dashboard/components/MetricCard.tsx`** — KPI metric card with sentiment coloring.

- **`dashboard/components/KillSwitch.tsx`** — Kill + Pause + Resume; U11 — no parameter editing.

- **`dashboard/components/PnLChart.tsx`** — lightweight-charts v5 `addSeries()` line chart;
  ResizeObserver for responsive layout; design-token colors from CSS vars.

- **`dashboard/components/WatchlistTable.tsx`** — Tier A/B watchlist table with pillar badge.

- **`dashboard/components/PositionsCard.tsx`** — Open positions with unrealised P&L coloring.

- **`dashboard/components/SignalFeed.tsx`** — Signal activity list with action badge.

- **`dashboard/components/RiskEventLog.tsx`** — Risk event log with severity badge.

- **`dashboard/components/HealthMonitor.tsx`** — Feed status, latency, WS count list.

- **`dashboard/hooks/useWebSocket.ts`** — WebSocket hook; 25s ping/pong keepalive; 3s auto-reconnect.

- **`dashboard/hooks/useDashboardState.ts`** — `DashboardProvider` context + reducer; hydrates from
  REST on mount; updates via WebSocket `state_update`, `signal`, `risk_event` messages.

- **`dashboard/lib/types.ts`** — TypeScript interfaces mirroring all Python Pydantic schemas.

- **`dashboard/lib/api.ts`** — Typed fetch wrapper; `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_API_KEY`
  env vars; all REST + control calls.

---

## [Phase 4] Paper Trading & Backtesting — 2026-06-26

Event-driven replay engine, conservative fill model, U6 simulator gate, live paper simulator,
§12 regression fixture tests. **483 passing / 3 skipped** (Postgres integration).

### Added

- **`core/backtest/__init__.py`** — Package; exports all Phase 4 public symbols.

- **`core/backtest/models.py`** — Domain models:
  - `TradeRecord`: one round-trip trade; tracks `vetoed`, `rule_violation`, `r_multiple`, all
    money in `Decimal`.
  - `SimDay`: per-day summary; computed properties `accuracy`, `wins`, `losses`, `day_trades`,
    `rule_violations`.
  - `BacktestResult`: aggregate over many `SimDay`s; properties `win_rate`, `avg_r`,
    `avg_hold_seconds`, `max_daily_drawdown`, `rule_violation_count`, `consecutive_green_days`.

- **`core/backtest/fill_model.py`** — Conservative fill model (optimistic fills forbidden):
  - `FILL_MODEL_DOC` — full documented assumptions (sub-$20 slippage, ECN fees, U13 cost).
  - `MENTAL_STOP_LATENCY_SLIP = Decimal("0.05")` — documented U13 cost vs resting stop.
  - Fee schedule (2026): FINRA TAF $0.000195/sh (sells, cap $9.79), exchange $0.0003/sh.
  - `entry_fill()` — limit @ ask+offset+slippage; 10% partial fill probability with seed.
  - `exit_fill_stop()` — U13 mental-stop fill: `min(stop−0.05, bar_low−0.01)` (always worse than a resting stop).
  - `exit_fill_target()` — sell at bid−slippage (spec §10).

- **`core/backtest/metrics.py`** — `BacktestMetrics` + `compute_metrics()`:
  - Fields: `total_trades`, `win_rate`, `avg_r`, `avg_hold_minutes`, `max_daily_drawdown`,
    `total_net_pnl`, `total_fees`, `rule_violation_count` (must be 0), `sim_gate_qualifying_days`,
    `consecutive_green_days`.

- **`core/backtest/sim_gate.py`** — `SimulatorGate` (U6 hard gate):
  - `record_day()` — accumulates or resets streak on failing day.
  - `satisfied` — True when ≥ SIM_GATE_DAYS consecutive days @ ≥ SIM_GATE_ACCURACY.
  - `live_mode_allowed()` — BOTH `satisfied` AND `LIVE_ENABLED=true` required. Neither alone is enough.
  - Default `LIVE_ENABLED=false` in config — must be manually set after client sign-off.

- **`core/backtest/replay.py`** — Deterministic event-driven backtest engine:
  - `ReplayBar` — one replay event (bar + scan + L2 + market context).
  - `replay()` — processes `Sequence[ReplayBar]` through `StrategyEngine → RiskManager →
    FillModel`; seed ensures determinism.
  - Day boundary: resets both engine and risk manager per date.
  - U13 mental stop: detected on `bar.low`; fills with `exit_fill_stop()` latency penalty.
  - U3 EOD flatten: positions closed at `EOD_FLATTEN_TIME`.
  - Every veto recorded as `TradeRecord(vetoed=True)` for audit.

- **`core/backtest/paper_session.py`** — Async live paper simulator:
  - `PaperSession` — orchestrates `StrategyEngine → RiskManager → BrokerAdapter` on live bars.
  - Mental-stop background task polls at 500ms; fires marketable-limit (never native STOP, U13).
  - EOD flatten task fires at `EOD_FLATTEN_TIME` (U3).
  - `ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"` documented.

- **`tests/test_backtest_fill_model.py`** — 35 fill model tests:
  - Entry fill always above ask+offset; fees Decimal; FINRA cap; partial fill via seed; deterministic.
  - Stop exit always below stop price (U13 latency documented); floor at $0.01.
  - Target exit below bid; FINRA cap fires at large lots.

- **`tests/test_backtest_sim_gate.py`** — 23 U6 gate tests:
  - Not satisfied initially; satisfied after ≥10 qualifying days; reset on failing day.
  - LIVE_ENABLED=false blocks live even when U6 satisfied; custom thresholds work.

- **`tests/test_backtest_replay.py`** — 23 replay engine tests:
  - Empty replay → zero days; day boundary → correct SimDay count; rule_violation_count = 0.
  - Latency model: `MENTAL_STOP_LATENCY_SLIP` exported, Decimal, $0.05; stop exit < stop price.
  - ReplayBar is frozen; BacktestResult properties sane on empty runs.

- **`tests/test_sec12_regression.py`** — 24 §12 fixture regression tests:
  - SLXN, MLGO: `RiskManager.evaluate()` → `approved=True`, `shares > 0`, no vetoes.
  - GLTO: `AVERAGE_DOWN` veto (add to red position → forbidden U2).
  - ESTR: `NO_FIVE_PILLAR` veto (`e1_universe=False` at risk layer → U1).
  - PALI: `SKIP_CATALYST` veto (`catalyst_skip=True`, secondary offering → U15).
  - PTPI: `SKIP_CATALYST` veto (buyout → U15).
  - GME: `HARD_STOP_TIME` veto (2PM ET, past 11AM gate → §7).
  - TRNR: `approval.shares ≤ liquidity_cap_shares` (thin book limits size → U9).
  - Three-strikes halt; daily loss limit; session reset clears state.

### Acceptance criteria met

- Full §12 fixture suite green (all 24 regression tests pass).
- `rule_violation_count = 0` over all sim runs (no U1–U15 breach escapes detection).
- U6 flag blocks live mode until `satisfied AND LIVE_ENABLED=true` (two-condition hard gate).
- Latency model present in fills: `MENTAL_STOP_LATENCY_SLIP` documented in `FILL_MODEL_DOC`,
  stop exit always below stop price, `exit_fill_stop()` returns worse fill than resting stop.
- Conservative fills enforced: optimistic fills are structurally impossible in `entry_fill()` and
  `exit_fill_stop()`.

---

## [Phase 3] Risk Management Layer — 2026-06-26

Pre-trade veto gate, position-sizing engine, live monitors, kill-switch.
**Risk Manager is the mandatory gate between Strategy and Execution.** No order reaches the broker
without passing `RiskManager.evaluate()`. 380 passing / 3 skipped (Postgres integration).

### Added

- **`core/risk/__init__.py`** — Package; exports `RiskManager`, `VetoReason`, `TradeApproval`,
  `GiveBackLevel`, `RiskState`.

- **`core/risk/models.py`** — Core DTOs:
  - `VetoReason` (StrEnum, 11 reasons): `NO_FIVE_PILLAR`, `RR_BELOW_MIN`, `DAILY_LOSS_LIMIT`,
    `GIVE_BACK_HARD`, `THREE_STRIKES`, `AVERAGE_DOWN`, `PDT_LIMIT`, `SKIP_CATALYST`,
    `HARD_STOP_TIME`, `HALTED`, `SIZING_ZERO`.
  - `GiveBackLevel` (StrEnum): `NONE`, `WARN`, `HALT`.
  - `TradeApproval` (frozen Pydantic): `approved`, `shares`, `vetoes`, `spec_ref`.
  - `RiskState` (mutable dataclass): `realized_pnl`, `peak_pnl`, `consecutive_losses`,
    `trades_today`, `halted`, `halt_reason`, `open_positions`.

- **`core/risk/pre_trade.py`** — Pure `evaluate_pre_trade()`:
  - Fast-path: `halted=True` → returns `[HALTED]` immediately.
  - U1: `e1_universe=False` → `NO_FIVE_PILLAR`.
  - 2:1 RR: `signal.rr_ratio < RR_MIN` → `RR_BELOW_MIN`.
  - U4 daily loss: `min(equity×10%, AVG_WIN_DAY_PNL, BROKER_HARD_LOCKOUT)` → `DAILY_LOSS_LIMIT`.
  - U4 give-back hard: `(peak−realized)/peak ≥ GIVE_BACK_HARD` → `GIVE_BACK_HARD`.
  - U5 three-strikes: `consecutive_losses ≥ THREE_STRIKES` → `THREE_STRIKES`.
  - U2 average-down: entry below open position for same symbol → `AVERAGE_DOWN`.
  - §13.11 PDT: `trades_today ≥ MAX_TRADES_PER_DAY` → `PDT_LIMIT`.
  - U15 SKIP-list: `catalyst_skip=True` → `SKIP_CATALYST`.
  - §7 time gate: `now_et_time > HARD_STOP_TIME` (strictly >) → `HARD_STOP_TIME`.
  - All applicable vetoes accumulate; callers see all violations at once.

- **`core/risk/sizing.py`** — Pure `compute_size()` (spec §6):
  - Mode: `risk_formula` (default) → `floor(PER_TRADE_RISK / risk_per_share)`; `flat_block` → `MAX_SIZE` or `STARTER_CAP`.
  - Cushion: `pnl ≤ 0` → clamp to icebreaker (`floor(MAX_SIZE × ICEBREAKER_FRACTION)`); `0 < pnl < threshold` → clamp to `STARTER_CAP`.
  - Conviction multiplier: `floor(raw × conviction_score)`.
  - DOW: Monday ×`DOW_MONDAY_MULT` (0.50), Friday ×`DOW_FRIDAY_MULT` (0.75), Wed/Thu unmodified.
  - Market state: `COLD` → ×`MARKET_STATE_COLD_MULT` (0.50); `REHAB` → `min(raw, MARKET_STATE_REHAB_CAP)`.
  - Liquidity cap: clamp to `liquidity_cap_shares` if `> 0` (0 = unconstrained = data unavailable).
  - MAX_SIZE ceiling: never exceeds `MAX_SIZE`.
  - Returns `max(0, result)`; zero triggers `SIZING_ZERO` veto in manager.

- **`core/risk/monitors.py`** — Five pure monitor functions:
  - `is_mental_stop_breached(current, stop)` → `current ≤ stop`; U13 caller fires marketable-limit, never native STOP.
  - `evaluate_give_back(realized, peak, cfg)` → `NONE / WARN / HALT`; WARN at ≥25%, HALT at ≥50%.
  - `is_daily_loss_limit(realized, equity, avg_win, cfg)` → True when loss exceeds effective limit.
  - `should_flatten_eod(now_et_time, cfg)` → True when `≥ EOD_FLATTEN_TIME` (default 15:55); U3.
  - `is_past_hard_stop_time(now_et_time, cfg)` → True when `> HARD_STOP_TIME` (strictly >).

- **`core/risk/manager.py`** — Stateful `RiskManager`:
  - `evaluate(signal, now_et, equity, liquidity_cap_shares, catalyst_skip)` → `TradeApproval`; the mandatory gate.
  - `record_open(symbol, entry_price)` — adds to `open_positions`, increments `trades_today`.
  - `record_close(symbol, pnl)` — removes from `open_positions`, updates `realized_pnl`, `peak_pnl`, `consecutive_losses`; fires three-strikes halt if streak ≥ 3.
  - `reset_session()` — replaces `RiskState` with fresh instance; re-enables trading next day.
  - `halt_session(reason)` — kill-switch; sets `halted=True`, records reason.
  - `check_mental_stop`, `check_give_back`, `check_daily_loss`, `should_flatten_eod` — live monitor delegates.

- **`core/config.py`** — 6 new Phase 3 config keys: `AVG_WIN_DAY_PNL`, `LIQUIDITY_CAP_FRACTION`,
  `MARKET_STATE_COLD_MULT`, `MARKET_STATE_REHAB_CAP`, `EOD_FLATTEN_TIME`, `DOW_FRIDAY_MULT`.

- **`tests/test_pre_trade.py`** — 31 tests (10 classes): every veto rule pass + fail; fast-path HALTED; multi-veto accumulation; clean-state acceptance.
- **`tests/test_sizing.py`** — 27 tests (8 classes): both modes, all caps, DOW × market-state × conviction matrix, liquidity, MAX_SIZE ceiling, degenerate stop → zero.
- **`tests/test_risk_monitors.py`** — 20 tests (5 classes): all five monitor functions; boundary values for give-back thresholds, daily-loss formula (all three binding components), EOD and hard-stop time gates.
- **`tests/test_risk_manager.py`** — 43 tests (8 classes): evaluate() happy path, all veto paths, full position lifecycle, three-strikes progression, reset, live monitor integration, liquidity-cap integration.

### Design decisions

- **Mandatory gate pattern**: `evaluate()` returns `TradeApproval`; nothing proceeds without `approved=True`. Vetoes are auditable for the `risk_events` ledger table (Phase 6).
- **No native STOP orders (U13)**: monitors return booleans; callers fire marketable-limit. Risk Manager never sends any order type directly.
- **SIZING_ZERO veto**: fires when `compute_size()` returns 0 (degenerate risk budget). Cannot happen via `stop ≥ entry` (that fires `RR_BELOW_MIN` first).
- **`trades_today` incremented at `record_open`**: correct for PDT pre-trade check (must count this trade before it happens).
- **`peak_pnl` is a high-watermark**: only moves up on wins, never down.

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
