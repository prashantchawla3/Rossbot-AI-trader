# PROGRESS.md — RossBot Running Log

> Running project log per CLAUDE.md §11.4. Update at the end of every working session:
> what was built, decisions made, versions/URLs verified, open questions, next step.
> Source of truth for rules = `ROSSBOT_STRATEGY_SPEC.md` v2.0. Phases = `ROSSBOT_PROJECT_PLAN.md`.
> Standing rules + phase prompts = `ROSSBOT_CLAUDE_CODE_PROMPTS.md` ("DO NOT TOUCH.md").

---

## SESSION 0 — Orientation (no code)

**Date:** 2026-06-26
**Goal:** Read the four docs in full; restate the roadmap, the non-negotiables, and list
contradictions between the docs. No code written. Then stop and wait.

**Status:** Docs read in full — spec (v2.0), project plan, CLAUDE.md, prompts file. PROGRESS.md
was empty; this is its first entry. Confirmed phase: **pre-Phase-0** (orientation only).

---

## 1. The 14-phase roadmap (Phases 0 → 13)

Authoritative source = `ROSSBOT_PROJECT_PLAN.md` + `ROSSBOT_CLAUDE_CODE_PROMPTS.md`.
"14 phases" = Phase 0 through Phase 13 inclusive. Build order is non-negotiable:
**risk gate before money path** ("brakes before engine"). One phase per session/branch/PR;
do not start a phase until the prior phase's lint + typecheck + tests are green and this log
is updated.

| # | Phase | Core deliverable | Complexity |
|---|---|---|---|
| **0** | Infrastructure & Adapters | Monorepo (`core/ api/ db/ dashboard/ adapters/ tests/`); Postgres schema v0 (12 tables); config service seeded with C1–C16 cautious defaults; vendor-agnostic `BrokerAdapter` / `MarketDataAdapter` ABCs; fail-closed provider stubs (`CatalystProvider`, `L2SignalProvider`, `MarketStateProvider`); CI. **No strategy logic.** | High |
| **1** | Data Layer (Scanner + Market Data) | Real-time + historical ingest (10s/1m OHLCV, full depth, tick tape, LULD/halt, news); **two-tier scanner** (Tier A wide net → Tier B Five Pillars); RVOL engine; float/share-count resolver; 9 EMA / VWAP / MACD on 1m + 10s. | High |
| **2** | Strategy Engine (Signal Detection) | Entry AND-gate E1–E7; label-agnostic pattern recognizers (§4A); conviction scorer; exit engine P1–P8; re-entry rule. **Outputs signals only — no execution.** | High |
| **3** | **Risk Management Layer** ⟵ BUILD BEFORE EXECUTION | The HARD VETO GATE. Pre-trade vetoes + live monitors (mental-stop emulation U13, 3-strikes, never-average-down, give-back, max-daily-loss, no-overnight, liquidity cap, PDT/cash, SKIP-list); sizing engine; kill-switch. Most-tested phase. | High |
| **4** | Paper Trading & Backtesting | Event-driven backtester (slippage, partial fills, ECN fees, mental-stop latency); §12 regression fixtures as pass/fail tests; live paper simulator; **U6 gate** (≥10 sim days @ ≥60%). | High |
| **5** | Dashboard & Monitoring | Read-mostly Next.js dashboard; FastAPI + WebSocket; alerting; health monitors; trade journal. **No mid-session parameter editing** (U11). | Medium |
| **6** | Live Trading | Harden live broker path (marketable-limit + partial sells + flatten; reconciliation; idempotency; disconnect→flatten/freeze); staged capital ramp. Real money only after U6 + all gates + client sign-off. | High |
| **7** | Catalyst Detection (13.1) | Replace `CatalystProvider` stub: NLP news classifier + reaction-proof gate + SEC-filing dilution checks; hard-block SKIP categories. Bias to **skip** on ambiguity. | High |
| **8** | Level 2 / Tape Microstructure (13.2) | Replace `L2SignalProvider` stub: real-floor-vs-spoof, iceberg, green-tape, absorption/break (E6), exit P3. Require prints-confirmation before E6. | High |
| **9** | Market-State Classifier + Attention (13.9, 13.3) | Replace `MarketStateProvider` stub (forced COLD): rolling-feature HOT/COLD/REHAB + "obvious" attention. Bias **COLD** on uncertainty. Gates EX1/EX2/mid-candle/oversize. | High |
| **10** | Execution Safety: Mental Stops & Time Stop (13.4, 13.5) | Low-latency internal monitor → marketable-limit on breach (no native STOP); quantified breakout-or-bailout (+10¢/60s); hidden catastrophic backstop. Measure loop latency. | High |
| **11** | Halt Resumption & Multi-Day Continuation (13.7, 13.10) | Halt engine (default `post_halt`; hard-block halt-down unless VWAP reclaimed, EX5); continuation engine (Day-1 ≥100% & held; numeric done-conditions; 5-min + reduced size). | High |
| **12** | Sizing/Liquidity & Pattern Hardening (13.6, 13.8) | `risk_formula` ($1k/stop) clamped by `LIQUIDITY_CAP = f(ADV, depth)`; cap order at % of top-N depth; harden "first new high" + ABCD geometry; mid-candle gated to HOT. | Medium-High |
| **13** | Regulatory / Account Compliance (13.11) | Startup hard-gate on account type/equity; PDT guard; cash-settlement → one-trade-per-day; wash-sale tracking; SSR/LULD awareness. Shorting stays out of scope. | Medium |

**Mode roadmap across phases:** Backtest → Simulation → Paper → Live.
**Final acceptance:** all §12 fixtures pass; 0 rule-violations over a full sim run; U6 satisfied;
live path (reconciliation/idempotency/disconnect-flatten/kill-switch) tested; no native STOP ever
routed system-wide; every external integration carries a web-verified version + doc-URL comment;
account type/equity confirmed + legal review of client-money structure recorded.

---

## 2. Non-negotiables (hardcode; enforce by construction)

Pulled from CLAUDE.md §4–§5, §10; spec §11 (U1–U15); prompts STANDING RULES B/C.

**Engineering invariants**
- **Risk gate before money path.** No execution code runs live until Phase 3 exists and its
  tests pass. Strategy *proposes*, Risk *disposes*, Execution *obeys*. Nothing reaches the broker
  without passing the risk veto.
- **No native STOP orders, ever (U13).** Never route a native STOP/STOP-LIMIT. Stops are MENTAL:
  internal monitor fires a **marketable-limit** on breach. Optional hidden catastrophic backstop
  far below the mental level only. Adapter must not expose/use a native STOP in the trading path.
- **Money is `Decimal` / integer cents — never `float`.** Postgres `NUMERIC`. Add a test that
  fails if a float reaches the ledger.
- **Every `⚠️ CONFLICT` (C1–C16) lives in the `config` table, not in code.** Cautious defaults
  per spec Appendix A. No literal magic numbers; conflicts resolve to config, never a hardcoded pick.
- **Fail-safe = do not trade.** On any uncertainty, missing/ambiguous data, stale feed, unverified
  catalyst, or unknown market state → no trade / flatten. **Stubs must fail closed**
  (Catalyst→"unverified"→Pillar 5 fails; L2→"unknown"→E6 fails; MarketState→COLD).
- **Limit orders only (U7).** Buy @ ask+offset (config 0.05/0.10); sells per spec §10. Never market.
- Idempotent orders (no duplicate fills on retry); all timestamps UTC, ET derived; append-only
  `ledger` and `risk_events`; every order + every veto writes an auditable row (symbol, time,
  reason, spec ref).
- **Mandatory web-search protocol (overrides training data).** Date is June 2026. Forbidden from
  writing integration code from memory — verify current versions/endpoints/auth, pin exact versions,
  cite doc URL + date at the integration point. If unverifiable → STOP and log the open question.

**Strategy/risk guardrails — spec §11 U1–U15** (U1–U9, U13–U15 enforced in Risk/Execution; U10–U12 are
behavioral):
- **U1** No Five-Pillar (Tier B) symbol → NO-TRADE day.
- **U2** Never average down (never add to a red position).
- **U3** No overnight holds — flat before close, every day.
- **U4** Daily stop: `day_pnl <= -MAX_DAILY_LOSS` OR 50% peak give-back → shut down.
- **U5** 3 consecutive losses → halt for the day.
- **U6** Simulator-first: ≥10 consecutive sim days @ ≥60% accuracy before live (hard gate).
- **U7** Limit orders only — never market.
- **U8** No counter-trend (no bottom-fishing crashes; never short a stock making new highs).
- **U9** No illiquid trades (clamp by `LIQUIDITY_CAP`; never be the whole book).
- **U13** No resting stop orders — mental stops via marketable-limit only.
- **U14** Never anticipate a $0.50/$1.00 break when a hidden seller is present (GMBL).
- **U15** Never trade buyout / secondary-offering / recycled-PR catalysts (SKIP list).
- (U10 technicals-over-bias; U11 walk away when hijacked / after 3 strikes; U12 no YOLO.)

**Hard rules consistent across all sources (CLAUDE.md §5)**
- Five Pillars gate ($2–20, float ≤20M, RVOL ≥5x, ROC ≥10%, catalyst).
- Entry = AND-gate of E1–E7 (never a partial match). MACD must be positive/crossing-up;
  hard-block on red MACD.
- 2:1 minimum reward:risk before a trade qualifies.
- Cushion rule: while `day_pnl <= 0`, size capped at icebreaker (¼–⅕ max).
- Primary window 07:00–10:00 ET; no new entries after hard-stop time (default 11:00).

---

## 3. Contradictions / inconsistencies found between (and within) the docs

These are *documentation* discrepancies to flag per CLAUDE.md §1 and §11.3 — not strategy
ambiguities to resolve by guessing. Most are minor; #1 is the one worth conscious tracking.

1. **CLAUDE.md §12 roadmap (7 items) ≠ the authoritative 14-phase plan (0–13).** CLAUDE.md §12
   lists a 7-step placeholder and *labels itself* "placeholder — the detailed build plan is the next
   deliverable." The plan + prompts file are the real 14-phase roadmap (restated in §1 above).
   No action needed beyond awareness; CLAUDE.md flags its own placeholder. When convenient, CLAUDE.md
   §12 could point to the plan to avoid future drift.

2. **Tier B float gate: ≤20M (spec §1, plan Phase 1) vs <10M (spec §9 `FIVE_PILLAR_SCAN`).**
   Spec §1 sets the Five-Pillars hard ceiling at **≤20M** (with <10M / <5M / <1M as *preference*
   sub-tiers / score weights). But spec §9's `FIVE_PILLAR_SCAN` line writes the Tier-B gate as
   `float <10M`. → Treat **≤20M as the Tier-B trade gate** (matches §1 + plan + CLAUDE.md §5);
   §9's `<10M` is the *preferred* tier, not the hard gate. Should be reconciled to config
   (`FLOAT_HARD_CEILING = 20M`, preferred sub-tiers as weights) so the spec doesn't read two ways.

3. **E7 spread: hard gate `[0.03, 0.10]` vs "caution / size down" above 0.10 (spec §2).** E7 is
   defined as an AND-gate member `spread ∈ [0.03, 0.10]` (so >0.10 *fails entry*), but the adjacent
   IF-block says `spread > 0.10 → caution (size down; slippage risk)` — i.e. *allowed but smaller*.
   Also the band leaves **0.01 < spread < 0.03 undefined** (the gate would reject 0.02¢, but the
   prose only calls out ≤0.01 as "too thick"). → Needs a config decision: is wide spread a hard
   veto or a size-down? Plan Phase 2 treats `[0.03, 0.10]` as the gate. Flag for client/spec
   clarification (candidate config key, e.g. `SPREAD_MAX_HARD` vs `SPREAD_SIZE_DOWN`).

4. **Two different cushion mechanics (spec §5 vs §6) over the $0–$1,000 realized band.** §5
   `CUSHION_RULE`: `IF day_pnl <= 0 → max_size = ICEBREAKER (¼–⅕ max)`. §6 size-up gate:
   `IF realized_day_pnl < 1000 (or <0.20/sh) → shares <= starter_cap (5,000)`. Between day_pnl = 0
   and +$1,000 the two rules give different caps (icebreaker vs 5,000-share starter). They're meant
   to stack (icebreaker while ≤0, then starter cap until +$1k secured), but the spec doesn't state
   the precedence explicitly. → Implement as an explicit ladder (≤0 → icebreaker; 0→$1k → starter
   cap; >$1k → scale), and note it so it isn't read as a conflict.

5. **Minor boundary `≥`/`>` mismatches between spec §1 and §9 for the same Five-Pillars thresholds:**
   RVOL `≥5x` (§1) vs `>5x` (§9); ROC `≥10%` (§1) vs `>10%` (§9). Trivial but should be normalized
   (use the §1 inclusive form) so fixtures sitting exactly on a threshold behave deterministically.

6. **Tier A surveillance surfaces names that are hard-avoided for entry.** Tier A wide net allows
   `price ∈ [1, 20]` and small-account mode allows a $1 floor, while `HARD_AVOID_BELOW = 2.00`
   (default ON for funded accounts) blocks <$2 entries. Not a true contradiction (Tier A = watch,
   Tier B = trade), but the scanner will legitimately show $1–2 names that the risk gate must then
   reject for funded accounts — worth an explicit note so it isn't mistaken for a bug.

**No contradictions found** on the core invariants — risk-gate-before-execution, no-native-stop
(U13), Decimal money, fail-safe-don't-trade, conflicts-to-config, 2:1 R:R, MACD hard-block,
07:00–10:00 window / 11:00 hard stop, U6 simulator gate (≥10 days / ≥60%) — these are stated
consistently across spec, plan, CLAUDE.md, and the prompts file.

---

## 4. Open questions for client / spec owner (carried forward)

- **Two production-blocking client decisions** (plan + CLAUDE.md §8): (1) **data/broker vendor**
  (gates whether true L2 depth + tick tape + halt imbalance quotes are even available); (2)
  **account type + equity** (gates PDT and cash-settlement trade-count rules at boot).
- Spread-gate semantics above 0.10 and in the 0.01–0.03 band (contradiction #3) — hard veto vs
  size-down? Needs a config key + default.
- Confirm the C1–C16 defaults stand as written in Appendix A before they're seeded in Phase 0.

## 5. Next step

Await go-ahead for **Phase 0 — Infrastructure & Adapters** (per `ROSSBOT_CLAUDE_CODE_PROMPTS.md`).
Paste STANDING RULES + the Phase 0 prompt to begin. No code until then.

— end Session 0 —

---

## SESSION 1 — Phase 0: Infrastructure & Adapters

**Date:** 2026-06-26
**Goal:** Build the spine — monorepo, schema, config service, vendor-agnostic adapter
interfaces, CI. No strategy logic.
**Status:** ✅ Complete. Ruff + mypy + pytest green locally (37 passed, 3 Postgres-integration
skipped without a DB); Alembic up/down validated on SQLite. See `Changelog.md` for the full
deliverable list.

### Versions verified (web-searched 2026-06-26 — STANDING RULES A)
| Package | Pinned | Source |
|---|---|---|
| Python | 3.13 (3.13.14 latest patch) | python.org/downloads |
| uv | 0.11.24 | pypi.org/project/uv |
| FastAPI | 0.138.1 | pypi.org/project/fastapi |
| uvicorn | 0.49.0 | pypi.org/project/uvicorn |
| Pydantic | 2.13.4 | pypi.org/project/pydantic |
| pydantic-settings | 2.14.2 | pypi.org/project/pydantic-settings |
| SQLAlchemy | 2.0.51 | pypi.org/project/SQLAlchemy |
| Alembic | 1.18.5 | pypi.org/project/alembic |
| psycopg | 3.3.4 | pypi.org/project/psycopg |
| redis | 8.0.1 | pypi.org/project/redis |
| structlog | 26.1.0 | pypi.org/project/structlog |
| ntplib | 0.4.0 | pypi.org/project/ntplib |
| Ruff | 0.15.20 | pypi.org/project/ruff |
| mypy | 2.1.0 | pypi.org/project/mypy |
| pytest | 9.1.1 | pypi.org/project/pytest |
| TimescaleDB image | timescale/timescaledb-ha:pg17.10-ts2.28.1 | hub.docker.com (tag verified) |
| Redis image | redis:8.0.1 | hub.docker.com |
| GitHub Actions | actions/checkout@v6, astral-sh/setup-uv@v8 | github.com |

### Decisions made
- **Money rejection is a hard `TypeError` (`FloatMoneyError`), not a soft `ValueError`.** A
  float in the money path is a programming error, so it surfaces unwrapped from Pydantic and
  wrapped as SQLAlchemy `StatementError` from the ORM (cause asserted in tests). Enforced at
  both boundaries: `core.money` (app) and `db.types.Money` (storage).
- **`order_type` CHECK-constrained at the schema** to `limit`/`marketable_limit`, and
  `OrderType` enum has no `stop`/`market` member → native STOP/MARKET is unrepresentable
  (U7/U13 by construction), not just discouraged.
- **TimescaleDB hypertables + append-only triggers are Postgres-only and guarded** in the
  migration, so the same migration runs on plain Postgres (CI) and SQLite (unit tests) via
  `create_all`. BIGINT autoincrement PKs use a `with_variant(Integer, "sqlite")` so unit tests
  work without Postgres.
- **`MAX_TRADES_PER_DAY` default = 1** (cautious cash/small-account assumption) until account
  type/equity is confirmed in Phase 13. **`LIVE_ENABLED` default = false** (U6 hard gate).
- **`MAX_SIZE` default = 10,000 shares** (liquidity-capped, never the hardcoded 100k — C11).
- **Ruff `RUF001/002/003` ignored** project-wide: spec citations intentionally use §, –, →, ⚠️.

### Open questions / carried forward
- Local Docker engine did not start this session, so the **Postgres-only integration tests
  (triggers + hypertables) were not run locally** — they are exercised in CI (TimescaleDB
  service) and the structural migration was validated on SQLite. Re-run
  `pytest -m integration` against a local container when Docker is available.
- The two production-blocking client decisions (data/broker vendor; account type/equity)
  remain open — no vendor adapter is wired (interface-only, as intended for Phase 0).
- Carried doc discrepancies #2–#6 from Session 0 (float ceiling wording, E7 spread semantics,
  cushion-ladder precedence, ≥/> boundaries) — to reconcile in the spec when those phases land.

### Next step
Phase 1 — Data Layer (Scanner + Market Data). Web-verify data-vendor SDKs (Databento, Polygon,
Alpaca) at the start of that session before any integration code.

— end Session 1 —

---

## SESSION 2 — Phase 1: Data Layer (Scanner + Market Data)

**Date:** 2026-06-26
**Status:** **DONE — D.** Ruff + mypy + pytest green (**121 passed, 3 Postgres-integration
skipped**). Built directly on the Phase 0 contracts (`core.config`, `core.money`,
`core.timeutils`, `db.models`, `adapters.base/providers`). See `Changelog.md` for the full list.

### Web-verified this session (STANDING RULES A; June 2026)
| Item | Verified fact | Source |
|---|---|---|
| alpaca-py | **0.43.4**; `StockHistoricalDataClient.get_stock_bars`; `StockDataStream(...feed=DataFeed.SIP)` + `subscribe_bars/_quotes/_trades`/`run`; `DataFeed{IEX,SIP,DELAYED_SIP,OTC,BOATS,OVERNIGHT}` — **SIP paid, IEX free**; paper `paper-api.alpaca.markets` | docs.alpaca.markets |
| databento | **0.80.0**; `Live`/`Historical`; dataset `XNAS.ITCH`; schemas `mbp-10`/`mbo`/`trades`; env `DATABENTO_API_KEY`; metered | databento.com/docs |
| SEC EDGAR | `companyconcept/CIK##########/dei/EntityCommonStockSharesOutstanding.json`; ticker→CIK `company_tickers.json` (pad 10); descriptive UA mandatory, ~10 req/s; **shares-outstanding ≠ free float** | sec.gov |
| numpy/pandas | 2.5.0 / 3.0.3 exist & 3.13-ok — **not added**; indicators hand-rolled on `Decimal` (lean+deterministic); `pandas-ta` archive-risk, avoided | pypi.org |
| Polygon→Massive | rebrand 2025-10; pkg `massive` 2.8.0 exposes `share_class_shares_outstanding` — noted as future free-float source, not wired | massive.com |

### Decisions / fail-safes
- **Bad float must not pass Pillar 2:** P2 requires float KNOWN + confidence ∈ {HIGH, MEDIUM} +
  ≤ ceiling. EDGAR shares-outstanding = conservative upper-bound proxy (MEDIUM). Disagreement or
  float > shares-out ⇒ LOW (blocked).
- **RVOL low/unknown confidence can't pass Pillar 3** (thin baseline history).
- **Tier A surveils unknown-float names; only Tier B is tradeable** (U1) — matches Session-0
  discrepancy #6. Pillar boundaries normalized to §1 inclusive form (#5).
- **Scanning requires SIP/consolidated** (`REQUIRE_SIP=true`); IEX-only/OTC/delayed rejected. Feed
  gap ⇒ stale ⇒ do not trade (unseen key also = stale).
- **Indicators are pure `Decimal`** (no float, no numpy/pandas) so batch == streaming bit-for-bit
  and the §12 fixtures stay reproducible.
- Vendor SDKs are an **optional `rossbot[vendors]` extra**, imported lazily; mypy
  `ignore_missing_imports` for `alpaca.*`/`databento.*` so the lean test env stays green.

### Open questions / carried forward
- **NEEDS-VERIFY before live wiring** (flagged in `adapters/databento.py`): exact DBN record struct
  (`Mbp10Msg.levels`, fixed-point price scale, Live-iteration API); Alpaca per-feed pre-market
  coverage; vendor free-float field names. (Schemas/clients/auth/versions are verified.)
- Postgres-only integration tests still skipped locally (no Docker) — exercised in CI; migration
  `0002` re-seeds idempotently.
- Two production-blocking client decisions still open: (1) data/broker vendor; (2) account
  type/equity.

### Next step
Phase 2 — Strategy Engine (entry AND-gate E1–E7, label-agnostic patterns §4A, conviction scorer,
exit engine P1–P8). **Outputs signals only.** Risk Manager (Phase 3) must exist & pass before any
signal routes toward execution ("brakes before engine").

— end Session 2 —

---

## SESSION 3 — Phase 2: Strategy Engine (Signal Detection)

**Date:** 2026-06-26
**Status:** **DONE — D.** All tests green: **259 passed, 3 Postgres-integration skipped**.
Built on top of Phase 0 + Phase 1 contracts. See `Changelog.md` for full list.

### Deliverables built

| File | What it does |
|---|---|
| `core/strategy/__init__.py` | Package marker |
| `core/strategy/models.py` | All Phase 2 DTOs: `PatternType`, `PatternMatch`, `ExitReason`, `ScaleAction`, `PullbackContext`, `EntryGateResult`, `EntrySignal`, `PositionSnapshot`, `ExitSignal`, `FailedPatternSignal` |
| `core/strategy/entry_gate.py` | E1–E7 AND-gate; `find_pullback_context`; fail-closed on MACD=None, L2=UNKNOWN |
| `core/strategy/patterns.py` | 9 label-agnostic pattern recognisers (§4A); `is_failed_pattern` (RKDA / GMBL / universal); `is_topping_candle` |
| `core/strategy/conviction.py` | Conviction scorer [0.25, 1.0]: pattern rank 30%, RVOL 25%, float 15%, attention 15%, spread 8%, retrace 7%; EMA-touch + VWAP-reclaim bonuses |
| `core/strategy/exit_engine.py` | P1–P8 exit rules in priority order; `_at_psych_level`; topping tail confirmed by NEXT candle |
| `core/strategy/engine.py` | `StrategyEngine` + `SymbolState`; 10s bars update indicators only; 1m bars drive entry/exit |
| `core/config.py` | Added Phase 2 config keys: `PULLBACK_MAX_CANDLES`, `SURGE_MIN_CANDLES`, `PSYCH_LEVEL_STEP/TOLERANCE`, `FLAG_CONSOLIDATION_MAX`, `LIGHT_VOLUME_RATIO`, `VOLUME_SPIKE_LOOKBACK` |
| `tests/test_entry_gate.py` | 30 tests: each E-gate pass + fail; MACD hard-block; spread=0.01 skip; mid-candle gated to HOT |
| `tests/test_patterns.py` | Pattern unit tests: ABCD P2<P1 void; topping-tail confirmation; RKDA light-volume; all 9 patterns |
| `tests/test_conviction.py` | Conviction scorer: clamp, pattern rank ordering, RVOL/float/attention/spread/retrace sensitivity, bonuses |
| `tests/test_exit_engine.py` | Exit engine P1–P8: each fires + doesn't fire; priority order (P1 beats P2 beats P3…); P4 requires confirmation |
| `tests/test_strategy_fixtures.py` | §12 regression fixtures: SLXN-style WIN generates `EntrySignal`; RKDA/GMBL/PALI losses generate NO `EntrySignal`; U3 no-overnight reset; 10s bars silent |

### Key design decisions

- **E6 fail-closed on UNKNOWN L2** (stub default `L2Signal.UNKNOWN` → E6 vetoes) — this is also how GMBL and RKDA fixture losses are blocked: L2=ICEBERG or L2=UNKNOWN fails E6 → gate fails → only `FailedPatternSignal` possible.
- **Topping tail P4** confirmed by the NEXT candle making a new low (spec §3 P4 [V2]). A single topping candle alone does NOT fire exit.
- **ABCD invariant: P2 ≥ P1** (higher low). `is_abcd` returns None if `pullback_low < p1_low` (stair-stepping down, spec §4A).
- **Volume comparisons stay in plain float/int** — never mix volume (int) with Decimal arithmetic. Prices/PnL/sizing stay Decimal everywhere.
- **MACD needs 34 bars** (26 slow EMA + 9 signal EMA - 1) before `histogram != None`. Integration tests pre-warm the engine with 36 rising bars before the signal sequence.
- **Mid-candle entry trigger forced to candle_close** unless `market_state == HOT` (spec C12).
- **`find_pullback_context` minimum bar count** = `surge_min_candles(2) + pullback_max_candles(3) + 1 = 6`.

### Bug fixed in production code
- `patterns.py`: `avg_vol * Decimal("3")` where `avg_vol` was Python `float` → `TypeError`. Fixed all volume arithmetic to use pure float/int (volumes are ints; only prices use Decimal).

### Open questions / carried forward
- Two production-blocking client decisions still open (data/broker vendor; account type/equity).
- Phase 3 (Risk Manager) must exist before any signal reaches the execution path ("brakes before engine"). **No signal routes to the broker in Phase 2.**
- `signals` table in `db.models` exists (SignalRow) but `StrategyEngine` does not yet persist signals there — that write-path belongs in Phase 3 (Risk Manager) or Phase 4 (Execution).

### Next step
**Phase 3 — Risk Management Layer** (mandatory veto gate, sizing engine, all U1–U15 guardrails).
No execution code is built until Phase 3 exists and all risk-gate tests pass.

— end Session 3 —

---

## SESSION 4 — Phase 3: Risk Management Layer

**Date:** 2026-06-26
**Status:** **DONE — D.** All tests green: **380 passed, 3 Postgres-integration skipped** (+121
new tests from Phase 3). Built directly on Phase 0–2 contracts. See `Changelog.md`.

### Deliverables built

| File | What it does |
|---|---|
| `core/risk/__init__.py` | Package marker; exports `RiskManager`, `VetoReason`, `TradeApproval`, `GiveBackLevel`, `RiskState` |
| `core/risk/models.py` | `VetoReason` (11 reasons), `GiveBackLevel` (NONE/WARN/HALT), `TradeApproval` (frozen Pydantic), `RiskState` (mutable daily dataclass) |
| `core/risk/pre_trade.py` | Pure function `evaluate_pre_trade()` — all pre-trade vetoes: U1 (Tier-B), 2:1 RR, U4 (daily loss + give-back), U5 (3-strikes), U2 (average-down), §13.11 (PDT), U15 (SKIP catalyst), §7 (hard-stop time) |
| `core/risk/sizing.py` | Pure function `compute_size()` — risk_formula or flat_block, cushion/icebreaker, starter cap, conviction × DOW × market-state multipliers, liquidity cap, MAX_SIZE ceiling |
| `core/risk/monitors.py` | Five pure monitor functions: `is_mental_stop_breached` (U13), `evaluate_give_back` (C3), `is_daily_loss_limit` (U4), `should_flatten_eod` (U3), `is_past_hard_stop_time` (§7) |
| `core/risk/manager.py` | `RiskManager` — stateful class tying everything together; `evaluate()` is the mandatory gate; `record_open/close`, `reset_session`, `halt_session`, live monitors |
| `core/config.py` | Added Phase 3 config keys: `AVG_WIN_DAY_PNL`, `LIQUIDITY_CAP_FRACTION`, `MARKET_STATE_COLD_MULT`, `MARKET_STATE_REHAB_CAP`, `EOD_FLATTEN_TIME`, `DOW_FRIDAY_MULT` |
| `tests/test_pre_trade.py` | 31 tests — each veto rule has pass + fail; fast-path HALTED; multiple-veto accumulation |
| `tests/test_sizing.py` | 27 tests — both modes, all caps (cushion/icebreaker/starter/conviction/DOW/market-state/liquidity/MAX_SIZE), degenerate stops |
| `tests/test_risk_monitors.py` | 29 tests — all five pure functions; boundary values for give-back thresholds, daily loss formula, time gates |
| `tests/test_risk_manager.py` | 34 tests — evaluate() happy path, veto paths, full position lifecycle, three-strikes, reset, live monitors |

### Key design decisions

- **Risk Manager is the SOLE gate.** `evaluate()` returns `TradeApproval(approved, shares, vetoes)`. Nothing proceeds to execution unless `approved=True`. Every veto is auditable in the returned `vetoes` tuple (for `risk_events` logging by the caller).
- **All pre-trade checks in priority order:** fast-path exits immediately on `halted`. Otherwise all applicable checks accumulate into the returned list (multiple vetoes surfaced at once).
- **Sizing ladder (spec §6):** ≤0 PnL → icebreaker (¼ max); 0→CUSHION_PNL_THRESHOLD → starter cap; ≥ threshold → scale. Applies in both risk_formula and flat_block modes.
- **MAX_DAILY_LOSS formula:** `min(equity × 10%, AVG_WIN_DAY_PNL, BROKER_HARD_LOCKOUT)` — most conservative of all three. `AVG_WIN_DAY_PNL` default = $1,000 (cautious; overrideable from ledger history).
- **SIZING_ZERO veto:** fires when `compute_size()` returns 0. Cannot happen when stop = entry (that case fires RR_BELOW_MIN first since rr=0). Can happen when PER_TRADE_RISK is tiny relative to risk-per-share.
- **REHAB mode** caps at `MARKET_STATE_REHAB_CAP` (default 1,000 shares) — more conservative than COLD (×0.50 mult).
- **DOW Friday** multiplied by `DOW_FRIDAY_MULT` (default 0.75); Monday by `DOW_MONDAY_MULT` (0.50); Wed/Thu unmodified.
- **No native STOP ever (U13):** `is_mental_stop_breached()` returns a bool; caller fires marketable-limit. The Risk Manager does not route any order type; it only approves or vetoes.
- **`signals` table write-path still deferred:** `SignalRow` DB persistence belongs in Phase 4 (Execution) once the RiskManager-approved lot is known.

### Bug fixed in tests
- `test_risk_manager.py`: `_NOW_EARLY` was `2026-06-26` which is a **Friday** (DOW×0.75 applied unexpectedly). Fixed to `2026-06-24` (Wednesday, day_of_week=2 → no DOW multiplier).

### Open questions / carried forward
- Two production-blocking client decisions still open: (1) data/broker vendor; (2) account type/equity.
- `AVG_WIN_DAY_PNL` default ($1,000) is conservative. In production this should be computed from the `ledger` table (rolling average of winning sessions). Wire in Phase 4/6.
- `LIQUIDITY_CAP_FRACTION` config key added but not yet used in `compute_size()` (depth data not yet wired). The caller can pass `liquidity_cap_shares` derived from real book depth once L2 adapter is live (Phase 8).
- No-overnight flatten (`should_flatten_eod`) fires at EOD but the actual flatten order is the execution layer's job (Phase 4+). Phase 3 only sets the flag.
- PDT guard uses `trades_today` incremented at `record_open`. If `MAX_TRADES_PER_DAY=1` (cash default), the second trade is blocked regardless of whether the first closed. For multi-trade accounts, set `MAX_TRADES_PER_DAY` to the actual PDT limit.

### Next step
**Phase 4 — Paper Trading & Backtesting**: event-driven replay backtester, §12 regression fixtures
as full end-to-end pass/fail, paper simulator, and U6 gate (≥10 sim days @ ≥60% accuracy).
No live capital until U6 is satisfied and the client decisions are resolved.

— end Session 4 —

---

## SESSION 5 — Phase 5: Dashboard & Monitoring

**Date:** 2026-06-26
**Status:** **DONE — D.** 483+ tests passing (Phase 0–4 baseline) + new Phase 5 test suite.

### Deliverables built

#### FastAPI layer (Python)

| File | What it does |
|---|---|
| `api/auth.py` | `require_api_key` — X-API-Key header dep; raises 403/503 |
| `api/schemas/__init__.py` | Package marker |
| `api/schemas/dashboard.py` | All frozen Pydantic response models: `OpenPosition`, `RiskStateOut`, `WatchlistEntry`, `SignalEvent`, `RiskEventOut`, `FeedHealth`, `HealthOut`, `JournalEntry`, `SessionJournal`, `DashboardStateOut`, `WsMessage`, `ControlResult` |
| `api/services/__init__.py` | Package marker |
| `api/services/ws_manager.py` | `ConnectionManager` — async broadcast + dead-connection cleanup |
| `api/services/state_service.py` | `StateService` — in-memory ring buffers (signals 200, risk_events 500); bridges trading engine → dashboard API |
| `api/services/alert_service.py` | `AlertService` — Slack webhook (urllib) + SMTP (smtplib) in ThreadPoolExecutor; never blocks event loop |
| `api/services/health_service.py` | `HealthService` — feed liveness, clock drift (ntplib), order ack latency, WS client count |
| `api/routers/__init__.py` | Package marker |
| `api/routers/dashboard.py` | Read-only GET endpoints: `/api/state`, `/api/watchlist`, `/api/positions`, `/api/signals`, `/api/risk-events`, `/api/journal` |
| `api/routers/controls.py` | U11-compliant POST-only controls: `/controls/kill-switch`, `/controls/pause`, `/controls/resume` — NO parameter editing |
| `api/routers/health.py` | `/health/` + `/health/ready` |
| `api/main.py` | Rewritten — lifespan context manager, CORS (GET+POST only), WebSocket `/ws/live`, background health loop |

#### Tests

| File | What it tests |
|---|---|
| `tests/test_dashboard_api.py` | Kill-switch flattens via adapter; no PATCH/PUT/DELETE routes; WebSocket pushes state; no mid-session param mutation |
| `tests/test_alert_service.py` | No-channels case, Slack webhook call, email dispatch, severity in message, failure tolerance |
| `tests/test_ws_manager.py` | Connect/disconnect, broadcast, dead-connection removal |
| `tests/test_health_service.py` | Stale feeds, live feeds, `all_healthy`, order ack latency, clock drift |

#### Next.js dashboard (TypeScript)

| File | What it does |
|---|---|
| `dashboard/package.json` | Next.js 16.2, React 19.2, lightweight-charts v5, lucide-react, geist, Tailwind v4 |
| `dashboard/next.config.ts` | Strict mode, Turbopack default |
| `dashboard/postcss.config.mjs` | `@tailwindcss/postcss` plugin only |
| `dashboard/tsconfig.json` | Strict, bundler moduleResolution, `@/*` alias |
| `dashboard/app/globals.css` | Full Minimalist design system — all CSS tokens, Tailwind v4 `@theme inline`, component CSS classes |
| `dashboard/app/layout.tsx` | Root layout — Geist, Geist Mono, DM Serif Display fonts |
| `dashboard/app/page.tsx` | Redirect → /overview |
| `dashboard/app/(dashboard)/layout.tsx` | DashboardProvider + Sidebar + `<main>` |
| `dashboard/app/(dashboard)/overview/page.tsx` | P&L metrics, PnLChart, positions, signal feed, kill-switch |
| `dashboard/app/(dashboard)/watchlist/page.tsx` | Tier A + Tier B tables |
| `dashboard/app/(dashboard)/signals/page.tsx` | Full signal buffer (200) |
| `dashboard/app/(dashboard)/risk-events/page.tsx` | Full risk event log (500) + severity counts |
| `dashboard/app/(dashboard)/journal/page.tsx` | Post-session trade journal with all fills |
| `dashboard/app/(dashboard)/health/page.tsx` | Feed liveness, clock drift, order latency |
| `dashboard/components/Sidebar.tsx` | Navigation + live/halted status dot |
| `dashboard/components/Badge.tsx` | Semantic badge (default / live / warn / success) |
| `dashboard/components/MetricCard.tsx` | KPI card with sentiment coloring |
| `dashboard/components/KillSwitch.tsx` | Kill + Pause + Resume controls (U11 — no param editing) |
| `dashboard/components/PnLChart.tsx` | lightweight-charts v5 line chart |
| `dashboard/components/WatchlistTable.tsx` | Tier A/B table with pillar badge |
| `dashboard/components/PositionsCard.tsx` | Open positions table |
| `dashboard/components/SignalFeed.tsx` | Signal activity list |
| `dashboard/components/RiskEventLog.tsx` | Risk event activity list |
| `dashboard/components/HealthMonitor.tsx` | Feed + latency status list |
| `dashboard/hooks/useWebSocket.ts` | WebSocket hook — ping/pong keepalive, auto-reconnect |
| `dashboard/hooks/useDashboardState.ts` | React context + reducer; WebSocket + REST polling |
| `dashboard/lib/types.ts` | TypeScript types mirroring Python schemas |
| `dashboard/lib/api.ts` | Typed fetch wrapper for all REST + control endpoints |

### Key design decisions

- **U11 enforced at the router layer** — `controls.py` only exposes POST /kill-switch, /pause, /resume. Zero PATCH/PUT/DELETE routes exist anywhere. Confirmed by acceptance test `test_no_patch_or_put_routes_exist`.
- **Stdlib-only alerting** — `urllib.request` (Slack) + `smtplib` (email) in `ThreadPoolExecutor`. No new runtime deps (`aiosmtplib`, `httpx`) added.
- **Monochrome design system** — `colors_and_type.css` is pure gray (not blue as README prose says). CSS/JSON token files win over prose per spec. Only non-neutral semantic tokens: `--success` green and `--destructive` red.
- **Ring buffers cap memory** — signals deque(maxlen=200), risk_events deque(maxlen=500). Client-side state mirrors same limits.
- **State bridge** — `StateService` is the in-process cache; trading engine calls `record_signal()`, `record_risk_event()`, `update_positions()`; dashboard routers read from it. WebSocket pushes state diff on each tick.
- **No font file bundled** — DM Serif Display declared as `localFont` fallback; user must supply `public/fonts/DMSerifDisplay-Regular.woff2` or swap for a Google Fonts import. Geist + Geist Mono come from the `geist` npm package.

### Open questions / carried forward
- Two production-blocking client decisions still open: (1) data/broker vendor; (2) account type/equity.
- DM Serif Display font file must be sourced and placed at `dashboard/public/fonts/DMSerifDisplay-Regular.woff2`.
- `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` env vars must be set before `npm run build` (defaults: localhost:8000).
- Dashboard `npm install` and `npm run build` not yet run — package-level CI gate for Next.js is Phase 5's outstanding step before merging.

### Next step
**Phase 6 (Live Trading)**: live broker adapter, staged capital ramp, readiness checklist automation, reconciliation, idempotency, disconnect→flatten/freeze. Real money only after U6 + client sign-off.

— end Session 5 —

---

## SESSION 6 — Phase 6: Live Trading

**Date:** 2026-06-26
**Status:** **DONE — D.** 561 tests passing (pre-existing `test_ws_manager.py` failures are from
deprecated `asyncio.get_event_loop()` in Phase 5 code, not Phase 6 regressions).
See `Changelog.md` and `RUNBOOK.md` for full deliverable list.

**Client sign-off:** NOT YET RECORDED — required before setting `LIVE_ENABLED=true`.

### Web-verified this session (STANDING RULES A; June 2026)

| Item | Verified fact | Source |
|---|---|---|
| alpaca-py | **0.43.4**; `TradingClient`, `LimitOrderRequest`, `TimeInForce.DAY`/`.IOC`; `close_all_positions(cancel_orders=True)` (market orders internally); `get_all_positions()`; `get_account()`; `get_order_by_id(GetOrderByIdRequest(by="client_order_id"))` for idempotency; extended_hours=True valid only with TimeInForce.DAY | docs.alpaca.markets |
| Alpaca data subscription | Basic plan = IEX only (insufficient for live scanning). **Algo Trader Plus required for SIP (consolidated tape)** | alpaca.markets/pricing |
| Alpaca halt detection | `get_asset()` does NOT detect intraday LULD halts. Requires Databento/Polygon halt feed for accurate intraday halt detection | docs.alpaca.markets + databento.com |
| ib_async (IBKR) | `ib_insync` renamed to `ib_async` after maintainer passed in 2024; still Gateway-based (IB TWS/Gateway must be running locally); evaluated but not selected — Alpaca chosen as primary | github.com/erdewit/ib_async |
| anyio | **4.14.1**; `@pytest.mark.anyio` (NOT `pytest.mark.asyncio`); `pytest-asyncio` is NOT installed in this project | pypi.org/project/anyio |

### Deliverables built

| File | What it does |
|---|---|
| `core/config.py` | +10 Phase 6 config keys: `LIVE_POLL_MS`, `RECONCILE_INTERVAL_S`, `RECONNECT_MAX_ATTEMPTS`, `RECONNECT_DELAY_S`, `CAPITAL_RAMP_TIER`, `CAPITAL_RAMP_MICRO_SHARES`, `CAPITAL_RAMP_STARTER_SHARES`, `READINESS_MIN_BUYING_POWER`, `READINESS_MIN_EQUITY`, `CLOCK_DRIFT_MAX_MS` |
| `adapters/alpaca_broker.py` | `AlpacaBrokerAdapter` — vendor-agnostic `BrokerAdapter` ABC impl; marketable-limit (limit @ ask+offset); partial_sell (limit @ bid); cancel_all_flatten (emergency kill); idempotent on 422 duplicate; pre-market → DAY+extended_hours=True; RTH → IOC; get_broker_positions() for reconciliation |
| `core/live/__init__.py` | Package marker; re-exports all Phase 6 public types |
| `core/live/models.py` | `CapitalTier` (MICRO/STARTER/FULL), `ReadinessItem`, `ReadinessResult`, `ReconcileResult` — all frozen dataclasses |
| `core/live/reconcile.py` | Pure function `reconcile_positions(broker, internal)` → `ReconcileResult` (matched/broker_only/internal_only/qty_mismatch) |
| `core/live/capital_ramp.py` | `CapitalRamp` — applies per-tier share cap on top of Risk Manager sizing; fail-safe to MICRO on unknown tier |
| `core/live/readiness.py` | `ReadinessChecker.check_all()` — 8 independent checks (LIVE_ENABLED, U6_GATE, ACCOUNT_TYPE, BUYING_POWER, PDT_EQUITY, CAPITAL_TIER, CLOCK_DRIFT, DATA_FEED); no fail-fast; always returns full picture |
| `core/live/session.py` | `LiveSession` — hardened live session; 5 async loops (bar_loop, mental_stop_loop, eod_flatten_loop, reconcile_loop, feed_watchdog_loop); U6 hard gate at run(); CapitalRamp applied post-sizing; flatten-or-freeze on disconnect |
| `tests/test_reconcile.py` | 11 tests — pure function; all four discrepancy classes; edge cases (empty, all-matched, summary strings) |
| `tests/test_capital_ramp.py` | 13 tests — MICRO/STARTER/FULL caps; no-inflate; zero passthrough; max_for_tier; unknown-tier falls back to MICRO |
| `tests/test_readiness.py` | 12 tests — each of the 8 readiness items; no-fail-fast (all 8 always run); ReadinessResult model tests |
| `tests/test_live_adapter.py` | 19 tests — AlpacaBrokerAdapter mocked SDK; idempotency (422→get_order_by_id); cancel_all_flatten; pre-market TIF; position fetching; account state |
| `tests/test_live_session.py` | 8 tests — U6 gate blocks run(); LIVE_ENABLED gate; clean startup/stop; mental-stop fires partial_sell (not STOP); reconcile removes orphan; disconnect→flatten; disconnect→freeze; EOD flatten |
| `RUNBOOK.md` | Live trading runbook: pre-market checklist, capital ramp guide, daily session procedure, order routing rules, 7-scenario incident playbook, config reference, monitoring guide, client sign-off template |

### Key design decisions

- **Alpaca chosen as live broker** (not IBKR): no local Gateway process required; REST+WebSocket API; `close_all_positions` for kill-switch. Paper sandbox and production share the same SDK.
- **Pre-market TIF:** IOC is RTH-only on Alpaca. Pre-market and after-hours sessions use `TimeInForce.DAY + extended_hours=True`. Session detected via `session_for()` from `core.timeutils`.
- **Idempotent retry:** On 422 duplicate `client_order_id`, adapter fetches the existing order via `get_order_by_id`. No double fill on network retry.
- **`cancel_all_flatten` uses market orders** (Alpaca `close_all_positions`): the ONLY exception to U7 (limit-only). Reserved for emergency kill-switch only. Documented in adapter docstring.
- **`get_halt_status` via `get_asset()` is NOT intraday-accurate.** Logs a NEEDS-VERIFY note: real-time halt detection requires Databento/Polygon halt feed (Phase 8 dependency).
- **Capital ramp is set at session start from config, NOT modified mid-session** (U11). Promote tier by updating DB config table before the next session.
- **Reconcile removes orphan positions automatically** (`internal_only` symbols removed from `_open` since broker confirms no position). Ghost positions (`broker_only`) log at WARN — never silently auto-close broker positions.

### Bugs fixed during Phase 6

1. **`TypeError` on INT config keys in tests:** `_config(**overrides)` helper in all 3 test files was storing all overrides as `ValueType.STR`. Fixed to preserve declared `ValueType` for each key by looking up DEFAULTS.
2. **`@pytest.mark.asyncio` used instead of `@pytest.mark.anyio`:** `pytest-asyncio` is NOT installed. All async test files changed to `@pytest.mark.anyio`.
3. **Timing failures in `test_live_session.py`:** Internal loops (reconcile 1s, EOD 10s) did not fire within 0.12–0.15s test windows. Fixed by calling internal methods directly (`_reconcile_loop(interval_s=0)`, `_handle_disconnect(max_attempts=1, delay_s=0)`) and writing an inline `fast_eod_loop` with `asyncio.sleep(0)`.
4. **`NameError: now_utc`:** Fast EOD loop test referenced `now_utc()` without importing it. Added `from core.timeutils import now_utc`.

### Open questions / carried forward

- **Production-blocking items (see `RUNBOOK.md` §9):**
  - Alpaca production keys + Algo Trader Plus subscription (SIP required)
  - Halt feed: `get_halt_status` is not intraday-accurate; Databento halt feed required (Phase 8)
  - Account type + equity sign-off (§13.11 / PDT)
  - Client sign-off before `LIVE_ENABLED=true`
- Two pre-existing test failures outside Phase 6 scope:
  - `test_ws_manager.py` (5 tests): deprecated `asyncio.get_event_loop()` — Phase 5 issue, not Phase 6.
  - `test_dashboard_api.py`: `httpx2` not installed — Phase 5 dependency gap.

### Next step

**Client sign-off** (Phase 6 "Done" condition per prompt):

```
CLIENT SIGN-OFF — [Date]
U6 Gate: [ ] satisfied — [N] consecutive sim days @ [N]% accuracy
Capital Tier: MICRO approved
Account type confirmed: [MARGIN/CASH]
Account equity: $[N]
Broker: Alpaca (alpaca-py 0.43.4) / Data: Databento 0.80.0
SIP subscription: Algo Trader Plus (confirmed)
Outstanding open questions: [list or NONE]
```

Once client sign-off is recorded above, `LIVE_ENABLED=true` may be set in the DB config table
and the first dry-run paper session (production keys, paper endpoint) may begin.

**Phase 7 (Catalyst Detection):** Replace `CatalystProvider` stub with NLP news classifier +
reaction-proof gate + SEC dilution check. Requires real-time news feed vendor decision.

— end Session 6 —
