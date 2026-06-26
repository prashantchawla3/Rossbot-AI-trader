# ROSSBOT_CLAUDE_CODE_PROMPTS.md
**Build prompts for Claude Code — RossBot, phase by phase, 0 → 13.**
Companions in repo: `ROSSBOT_STRATEGY_SPEC.md` (rules, source of truth), `ROSSBOT_PROJECT_PLAN.md` (phases), `CLAUDE.md` (project context), `progress.md` (running log).

---

## HOW TO USE

1. Run **one phase per Claude Code session** (one branch, one PR). Don't batch phases — each has a hard "Definition of Done" gate.
2. **Paste `STANDING RULES` once at the start of every session**, then paste that phase's prompt. (Or tell Claude Code: "Re-read STANDING RULES in ROSSBOT_CLAUDE_CODE_PROMPTS.md before this phase.")
3. **Session 0 (orient), before Phase 0:** paste this →
   > Read `ROSSBOT_STRATEGY_SPEC.md`, `ROSSBOT_PROJECT_PLAN.md`, `CLAUDE.md`, and `progress.md` in full. Do not write code. Restate, in `progress.md`, the 14-phase roadmap, the non-negotiables (risk gate before execution, no native stop orders U13, money as Decimal, fail-safe = don't trade, all C1–C16 conflicts live in the config table), and list any contradictions you find between the docs. Then stop and wait.
4. Do not start a phase until the previous phase's tests + typecheck + lint are green and `progress.md` is updated.

---

## STANDING RULES (apply to EVERY phase — read first, every session)

**A. MANDATORY WEB-SEARCH PROTOCOL — THIS OVERRIDES YOUR TRAINING DATA.**
The date is **June 2026**. Your training data is stale for anything version-, API-, SDK-, pricing-, auth-, or vendor-feature-specific. You are **forbidden from writing integration code from memory.**

Before writing ANY code that touches an external API, SDK, library, package version, CLI, auth flow, webhook, data feed, or vendor feature, you MUST:
1. `WebSearch` / `WebFetch` the **current official docs** and confirm: current package version, current method/endpoint signatures, current auth scheme, current rate limits, and any breaking changes since early 2026.
2. Pin exact versions in the dependency manifest based on what you found — never a guessed version.
3. Add a one-line comment at the integration point citing the doc URL + date checked, e.g. `# verified: docs.alpaca.markets/... (2026-06)`.
4. If search shows the API differs from what you "remember," **follow the current docs, not memory.**
5. If you cannot verify something, **STOP and write the open question into `progress.md` — do not guess and do not fabricate endpoints, fields, or keys.**

Things you MUST web-search every time they come up (non-exhaustive): Alpaca API/SDK (`alpaca-py`), Databento client, IBKR API + its current Python lib (note: `ib_insync` status changed — verify the maintained library in 2026), TradeStation WebAPI, Polygon/Massive, Benzinga, SEC EDGAR endpoints, Postgres + TimescaleDB versions, FastAPI, Pydantic (v2 vs newer), SQLAlchemy, Alembic, Redis client, Next.js + React versions, charting libraries, `uv`/Poetry, Ruff, mypy/pyright, Python 3.11/3.12/3.13 support status, Docker base images.

**B. NON-NEGOTIABLE ENGINEERING INVARIANTS.**
- **Risk gate before money path.** No execution code may run live until Phase 3 exists and its tests pass. Strategy output routes through the risk manager's hard veto — never directly to a broker.
- **No native STOP orders, ever (U13).** Stops are emulated by an internal monitor firing a marketable-limit on breach. The broker adapter must not expose or use a native STOP type in the trading path.
- **Money is `Decimal` / integer cents. Never `float`.** Enforce with types; add a test that fails if a float reaches the ledger.
- **Every `⚠️ CONFLICT` (C1–C16) lives in the `config` table, not in code.** Cautious defaults per spec Appendix A.
- **Fail-safe = do not trade.** On any uncertainty, missing data, stale feed, unverified catalyst, or unknown market state → no trade / flatten. Stubs must fail closed (see Rule C).
- **Limit orders only.** Buy @ ask+offset (config 0.05/0.10); sells per spec §10.
- Idempotent orders (no duplicate fills on retry). All timestamps UTC, ET derived. Append-only `ledger` and `risk_events`.

**C. STUB-THEN-HARDEN PATTERN.**
Phases 7–13 fill in the hard ML/microstructure logic. Earlier phases depend on it via **interfaces with fail-closed stubs**:
- `CatalystProvider` stub → returns "unverified" → Pillar 5 fails → no trade.
- `L2SignalProvider` stub → returns "unknown" → E6 fails → no trade.
- `MarketStateProvider` stub → returns `COLD` (most conservative) → blocks EX1/EX2/mid-candle/oversize.
Define these interfaces in Phase 0/2 and never let a stub default to a permissive value.

**D. DEFINITION OF DONE (every phase).**
1. Lint (Ruff) + typecheck (mypy/pyright) + tests (pytest) all green in CI.
2. New behavior covered by tests; fail-safe paths tested.
3. `progress.md` updated: what was built, decisions made, **versions/URLs verified via web search**, open questions, what the next phase needs.
4. Conventional-commit PR scoped to this phase only.

**E. STYLE.** Be direct. Don't over-engineer beyond the phase. When you hit a real fork (vendor, threshold, schema), present 2–3 options with trade-offs in `progress.md` and pick the cautious default, flagging it for client sign-off. Don't silently resolve a spec conflict.

---

## PHASE 0 — Infrastructure & Adapters

**Goal:** the spine. Monorepo, schema, config service, vendor-agnostic adapter interfaces, CI. No strategy logic yet.

**Read first:** `ROSSBOT_PROJECT_PLAN.md` Phase 0; spec §10, §13.11, Appendix A.

**Web-search before coding:** current stable versions + setup of — Python (3.11/3.12/3.13 status), `uv` or Poetry, Ruff, mypy, pytest, FastAPI, Pydantic, SQLAlchemy, Alembic, Postgres + TimescaleDB extension, Redis + Python client, Docker images, GitHub Actions syntax. Verify Pydantic settings/`pydantic-settings` current API for config + secrets.

**Build:**
- Monorepo: `core/` `api/` `db/` `dashboard/` `adapters/` `tests/`. Dependency manifest with **web-verified pinned versions**.
- `docker-compose.yml`: Postgres(+TimescaleDB), Redis. `.env.example` (no real secrets).
- Postgres schema v0 via Alembic: `symbols, bars, quotes, depth_snapshots, tape_prints, signals, orders, fills, positions, ledger, risk_events, config`. `NUMERIC` for all money. Append-only triggers on `ledger`, `risk_events`.
- `config` service: table + typed loader, seeded with C1–C16 cautious defaults (Appendix A). Reject literal magic numbers in code (add a lint/test check where feasible).
- **Adapter ABCs** in `adapters/`: `BrokerAdapter` (`submit_marketable_limit`, `partial_sell`, `cancel_all_flatten`, `account_state`, `get_halt_status`) and `MarketDataAdapter` (`subscribe_depth`, `subscribe_tape`, `subscribe_bars`, `get_quote`, `news_stream`). Plus provider interfaces `CatalystProvider`, `L2SignalProvider`, `MarketStateProvider` (fail-closed stubs per Rule C).
- Structured logging (JSON), secrets via env, NTP/clock-drift check util, UTC/ET time helpers.
- CI: lint + typecheck + unit tests on PR.

**Tests / acceptance:** schema migrates up/down clean; config loader returns seeded C1–C16; a `float`-into-ledger test fails as designed; adapter ABCs can't be instantiated; stubs fail closed. CI green.

**Done:** per STANDING RULES D.

---

## PHASE 1 — Data Layer (Scanner + Market Data)

**Goal:** real-time + historical data, two-tier scanner, indicators, float resolver.

**Read first:** plan Phase 1; spec §1, §9, §2A.

**Web-search before coding:** confirm the chosen data vendor's **current** API — default plan = **Alpaca (bars/quotes, paper)** + **Databento (TotalView-ITCH full depth + tick tape)**. Verify Databento current schemas (MBP-10/MBO), Python client, auth, metered pricing; Alpaca market-data SIP vs IEX feeds and pre-market coverage; SEC EDGAR endpoints for share-count/float; Polygon/Massive if used for fundamentals. Verify VWAP/EMA/MACD library choices (or implement; verify current `pandas`/`polars`/`numpy`).

**Build:**
- Streaming ingest: 10-sec + 1-min OHLCV, top-of-book quotes, **full depth**, **tick tape**, LULD/halt feed, news feed → normalized into schema. Build own bars from tape with explicit pre-market/odd-lot rules (document them).
- **Two-tier scanner** (§1/§9): Tier A wide net (gap≥4%, RVOL≥2x, float≤50M, $1–20) → Tier B Five Pillars gate ($2–20, float≤20M, RVOL≥5x, ROC≥10%, catalyst-present-flag from `CatalystProvider`). Sub-scanners: top-gainers, low-float-top-gainer, HOD-momentum, running-up (5%/5min), halt, reverse-split/IPO, continuation.
- RVOL engine (rolling 50-day baseline). Float/share-count resolver (vendor + EDGAR, with validation + confidence flag; bad float must not silently pass Pillar 2).
- Indicators on stream: 9 EMA, VWAP, MACD on 1-min and 10-sec.
- Historical warehouse for backtest (≥2 yrs tick/L1; depth where affordable).

**Tests / acceptance:** scanner unit tests with synthetic tickers (boundary cases at each threshold); SIP-vs-IEX guard (reject IEX-only for scanning); indicator values verified against a known fixture; float resolver flags low-confidence. Feed-staleness detector trips on a gap.

**Done:** D.

---

## PHASE 2 — Strategy Engine (Signal Detection)

**Goal:** entry AND-gate, patterns, conviction score, exit engine. **Outputs signals only — no execution.**

**Read first:** plan Phase 2; spec §2, §2A, §3, §4/4A, §12 fixtures.

**Web-search before coding:** only if introducing a TA/pattern library; otherwise implement geometrically. Verify current `pandas`/`polars` APIs used.

**Build:**
- Entry AND-gate E1–E7 (§2): universe(TierB), pullback 1–3 red (never chase vertical), candle-over-candle new high, MACD positive (hard block if red), retrace held (`RETRACE_MAX` 0.50 / preferred 0.25), L2 support via `L2SignalProvider` (stub→fail closed), spread ∈ [0.03, 0.10].
- Pattern recognizers (§4A), **label-agnostic geometry**: micro-pullback (highest), ABCD (P2≥P1, break H1), bull-flag/flat-top, gap-and-go, VWAP break, red-to-green, halt-resumption, reverse-split squeeze. Universal failed-pattern/invalidation set.
- Conviction scorer → feeds sizing (pattern rank, RVOL, float tier, attention, spread).
- Exit engine P1–P8 (§3): mental hard stop, time-stop (+10¢/60s), L2/tape reversal, topping-tail (confirm next candle new low), scale-into-strength + move-to-BE, first-red-close, VWAP guard, lost-popularity. Re-entry rule (fresh setup, not revenge).
- `ENTRY_TRIGGER` config: `candle_close` default; `mid_candle` only if `MarketStateProvider`=HOT.

**Tests / acceptance:** each E-gate has pass + fail tests; MACD-red hard-blocks; spread=0.01 skips; ABCD with P2<P1 voids; topping-tail needs confirmation candle; every signal carries a conviction score. Wins from §12 fixtures generate signals; the §12 losses that are setup-level (RKDA light-volume breakout, GMBL hidden-seller) do not.

**Done:** D. (Signals land in `signals` table; nothing routes to a broker.)

---

## PHASE 3 — Risk Management Layer ⟵ BUILD BEFORE EXECUTION

**Goal:** the HARD VETO GATE. Strategy → Risk → (only if approved) execution interface.

**Read first:** plan Phase 3; spec §5, §6, §11 (U1–U15), Appendix A/B.

**Web-search before coding:** PDT / cash-settlement (T+1) / wash-sale / SSR / LULD **current rules** (FINRA/SEC) — verify, don't assume.

**Build:**
- Pre-trade veto (all must pass or kill): Five-Pillar confirm (else NO_TRADE_DAY U1); 2:1 R:R reachable; cushion rule (day_pnl≤0 → cap ICEBREAKER); spread gate; `LIQUIDITY_CAP=f(ADV,depth)` (never become the book); PDT/cash/max-trades-per-day guard; catalyst SKIP-list block (buyout/secondary/recycled-PR/pump/5c-tick).
- Live monitors: **mental-stop emulation (U13)** — internal monitor → marketable-limit on breach, never native STOP; optional hidden catastrophic backstop far below. Three-strikes halt; never-average-down block; give-back (warn 25%/hard 50%); max-daily-loss `min(10% acct, avg win day)`; broker hard-lockout (default $5k); no-overnight flatten.
- Sizing engine: `SIZING_MODE` risk_formula default (`$1k/stop`) vs flat_block; clamp by `LIQUIDITY_CAP`; never hardcode max 100k (C11). Day-of-week (Mon ×0.5) + market-state weighting hooks.
- Global kill-switch / `cancel_all_flatten`. Every veto + fire → `risk_events`.

**Tests / acceptance (this is the most-tested phase):** a unit test per veto proving it fires; oversize beyond `LIQUIDITY_CAP` rejected; averaging-down blocked; 3 losses halts; give-back 50% shuts down; mental-stop fires marketable-limit and **no native STOP is ever sent** (assert on adapter calls); §12 loss fixtures (GLTO oversize-while-red, ESTR FOMO oversize, PALI secondary, PTPI buyout, GME after-hours/2PM) are all **vetoed**.

**Done:** D. Execution may only be wired after this is green.

---

## PHASE 4 — Paper Trading & Backtesting

**Goal:** event-driven backtester, §12 regression fixtures, live paper simulator, U6 gate.

**Read first:** plan Phase 4; spec §12 (all fixtures), U6.

**Web-search before coding:** Alpaca **paper** trading API current endpoints/behavior; any backtest framework only if used (prefer in-house event loop). Verify ECN/regulatory fee schedule for fill modeling.

**Build:**
- Event-driven replay over historical tape/depth: scanner → entry → risk → exit, deterministic. Model slippage, partial fills, spread, ECN fees, **mental-stop latency**. Conservative fills for thin sub-$20 names (optimistic fills are forbidden — document the model).
- Regression suite: every §12 labeled trade → pass/fail test. Wins must trigger + be approved; losses must be vetoed or exited per rule.
- Live paper simulator: full pipeline on live data → paper broker, zero real money.
- **U6 gate in config:** ≥10 consecutive sim days @ ≥60% accuracy required before any live capital; hard-enforced flag. Metrics: per-trade R, win rate, avg hold, give-back, max DD, rule-violation count (must be 0).

**Tests / acceptance:** full §12 fixture suite green; rule-violation count = 0 over a sim run; U6 flag blocks live mode until satisfied; latency model present in fills.

**Done:** D.

---

## PHASE 5 — Dashboard & Monitoring

**Goal:** read-mostly Next.js dashboard + FastAPI/WebSocket + alerting + health.

**Read first:** plan Phase 5; spec §11 (U11 — no mid-session emotional tampering).

**Web-search before coding:** **current Next.js + React versions** and app-router conventions; current charting lib for candles/L2 (e.g. lightweight-charts / tradingview / recharts — verify current); FastAPI WebSocket patterns; auth library current.

**Build:**
- Dashboard (read-mostly): live watchlist (Tier A/B), positions, signal feed, `risk_events` log, day P&L vs guard thresholds, **kill-switch** + pause. **No parameter editing mid-session** (mirrors U11) — config changes only out of session.
- FastAPI endpoints + WebSocket push. Alerting (Slack/email) on risk events, lockouts, disconnects, feed gaps. Health monitors: feed liveness, clock drift, order-ack latency, depth-stream staleness. Post-session trade journal/report.

**Tests / acceptance:** kill-switch flattens via adapter in a sim; WebSocket pushes state; alert fires on simulated feed gap; dashboard exposes no mid-session parameter mutation.

**Done:** D.

---

## PHASE 6 — Live Trading

**Goal:** harden the live path. Real money only after U6 + all gates.

**Read first:** plan Phase 6 + "Hard gates before any live capital"; spec §5/§6 capital ramp.

**Web-search before coding:** **final live broker's current API** (IBKR Python lib status in 2026 / TradeStation WebAPI) — order types, partial sells, position reconciliation, session/Gateway requirements, pre-market from ≥7AM ET, market-data licensing (non-pro vs pro). Verify before writing a single live order.

**Build:**
- Live broker adapter: real marketable-limit + partial sells + `cancel_all_flatten`; reconcile against broker positions every loop. Idempotent orders. Disconnect/recovery → **flatten-or-freeze, never trade blind**.
- Staged capital ramp (micro → starter cap → full) gated by realized cushion. Pre-market readiness checklist automation (account type, buying power, feeds, halt feed, clock). Live runbook + incident playbook.

**Tests / acceptance:** position-reconciliation test; duplicate-fill-on-retry test (must not double); disconnect → flatten/freeze test; U6 + account-type + data-feed gates block go-live until satisfied. **Dry-run on paper/live broker sandbox before real capital.**

**Done:** D + explicit client sign-off recorded in `progress.md` before enabling real money.

---

## PHASE 7 — Catalyst Detection (13.1)

**Goal:** replace `CatalystProvider` stub with a real NLP classifier + filing checks.

**Web-search before coding:** **current** news vendor API (Benzinga Pro or equivalent), SEC EDGAR/BAMSEC endpoints for S-1/S-3/424B (dilution), 13D/13G, Form 4; current NLP/LLM-classification approach + any model API used (verify versions/pricing/limits).

**Build:** classifier tagging FDA/M&A/offering/contract/theme; reaction-proof gate (`≥10% AND ≥5x RVOL`); hard-block SKIP categories (buyout, secondary, recycled-PR, pump, 5c-tick) via keyword + filing check. **Bias to skip on ambiguity** (false negative is safe).

**Tests / acceptance:** PALI (secondary) and PTPI (buyout) classified SKIP; a clean FDA catalyst passes only with reaction proof; ambiguity → skip. Provider no longer fails closed by default but still skips on low confidence.

**Done:** D.

---

## PHASE 8 — Level 2 / Tape Microstructure Engine (13.2)

**Goal:** replace `L2SignalProvider` stub with real depth/tape logic.

**Web-search before coding:** confirm **Databento TotalView** schema/fields in current docs (MBP-10/MBO), update cadence, reconnection; tick-tape semantics.

**Build:** real-floor-vs-spoof detector; iceberg detector (executed ≫ displayed-ask, no price advance); green-tape rate; absorption/break trigger (E6); exit signal P3. **Require prints-confirmation before E6 fires.**

**Tests / acceptance:** spoof (vanishing bid, no prints) → not support; iceberg (GMBL/NIXX-style) → no-buy / exit; absorption-then-break → E6 fires; CADL bid-pull trap → not treated as guaranteed support.

**Done:** D.

---

## PHASE 9 — Market-State Classifier + Attention (13.9, 13.3)

**Goal:** replace `MarketStateProvider` stub (was forced COLD) with real HOT/COLD/REHAB + "obvious" attention.

**Web-search before coding:** only if using an ML lib — verify current versions; otherwise rolling-feature heuristic.

**Build:** rolling features (gapper follow-through %, breakout success %, avg green/red day size, count of >100% / <5M-float names) → HOT/COLD/REHAB; %-gain rank + RVOL percentile + mention velocity for "obvious" (score weight, never a hard gate). **Bias COLD on uncertainty** — gates EX1/EX2/mid-candle/oversize.

**Tests / acceptance:** synthetic HOT tape unlocks mid-candle/EX2; synthetic COLD locks them; uncertain → COLD. Attention stays a weight, not a gate.

**Done:** D.

---

## PHASE 10 — Execution Safety: Mental Stops & Time Stop (13.4, 13.5)

**Goal:** measure and harden the no-native-stop path + breakout-or-bailout.

**Web-search before coding:** broker's marketable-limit fill behavior + latency characteristics (current docs); time-sync best practices.

**Build:** low-latency internal monitor → marketable-limit on breach (no native STOP); quantified breakout-or-bailout (`unrealized < +0.10 at T+60s AND no higher-highs on rising volume → flatten`); hidden catastrophic backstop far below mental level. Measure loop latency; tune `BAILOUT_SECONDS`/`BAILOUT_MOVE` per regime (backtested).

**Tests / acceptance:** breach fires marketable-limit within measured latency budget; **assert no native STOP is ever routed**; bailout fires on stall, not on slow-but-valid mover (tune + test both); backstop placed below mental level.

**Done:** D + recorded latency numbers in `progress.md`.

---

## PHASE 11 — Halt Resumption & Multi-Day Continuation (13.7, 13.10)

**Goal:** halt engine + continuation engine.

**Web-search before coding:** **current** LULD/halt mechanics + which broker exposes imbalance/resumption/reopen-auction quotes (verify — many retail hide it); whether the live broker trades the reopen.

**Build:** halt engine default `post_halt` (consume LULD + reopen auction; enter only if resume ≥ prior price with green prints; **hard-block halt-down** unless VWAP reclaimed — EX5). Continuation engine: eligibility Day-1 ≥100% & held close; done-conditions numeric (RVOL<25% prior, retrace>50%, MACD cross, VWAP loss); auto-switch to 5-min + reduced size.

**Tests / acceptance:** halt-down resumption (EX5) blocked unless VWAP reclaimed; ARM/CTRM/PHVS-style dip-and-rip fixtures trigger; continuation done-conditions exit Day-2 correctly.

**Done:** D.

---

## PHASE 12 — Sizing/Liquidity & Pattern Hardening (13.6, 13.8)

**Goal:** final sizing clamp + pattern-timing hardening.

**Web-search before coding:** none required unless a new lib is added (verify versions).

**Build:** `risk_formula` ($1k/stop) default clamped by `LIQUIDITY_CAP=f(ADV,depth)`; cap order at % of top-N-level depth; harden "first new high" timing + ABCD label-agnostic geometry; mid-candle gated to HOT only.

**Tests / acceptance:** oversize → self-slippage scenario (TRNR/ESTR) capped; depth-% cap enforced on every order; mid-candle blocked in COLD.

**Done:** D.

---

## PHASE 13 — Regulatory / Account Compliance (13.11)

**Goal:** startup hard-gate + ongoing compliance guards.

**Web-search before coding:** **current** PDT (<$25k → ≤3 day-trades/5 days), cash-settlement T+1, wash-sale, SSR, LULD rules (FINRA/SEC/IRS) — verify each against current sources.

**Build:** startup hard-gate confirming account type/equity; PDT guard; cash-settlement → one-trade-per-day; wash-sale tracking on high-frequency re-entries; SSR/LULD awareness wired into halt logic. Shorting remains out of scope (locate/HTB deferred) — assert it's disabled.

**Tests / acceptance:** <$25k margin account blocks the 4th day-trade in 5; cash account enforces one-trade-per-day; PDT violation can never be reached in any path; wash-sale flagged on rapid re-entry.

**Done:** D.

---

## PROJECT COMPLETE — final acceptance

All green before declaring done:
1. All §12 fixtures pass (wins trigger, losses vetoed/exited).
2. Zero rule-violations across a full sim run.
3. U6 gate satisfied (≥10 sim days @ ≥60%).
4. Live path: reconciliation, idempotency, disconnect→flatten/freeze, kill-switch all tested.
5. No native STOP ever routed (asserted system-wide).
6. Every external integration carries a web-verified version + doc-URL comment.
7. Account type/equity confirmed; PDT/cash rules enforced; legal review of client-money structure recorded.
8. `progress.md` reflects all decisions, verified versions, and the two open client decisions (broker/data vendor; account type) resolved.
