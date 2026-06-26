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
