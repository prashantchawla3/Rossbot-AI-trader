# ROSSBOT_PROJECT_PLAN.md
**Automated Day-Trading Bot — Ross Cameron (DaytradeWarrior) Replication**
**Companion to:** `ROSSBOT_STRATEGY_SPEC.md` v2.0 (source of truth for all rules)
**Mode roadmap:** Backtest → Simulation → Paper → Live
**Stack:** Python 3.11+ (core), FastAPI (backend), PostgreSQL (data/ledger), Next.js (dashboard)

> Build order is non-negotiable: **risk gate before money path** ("brakes before engine"). Every phase ships paper/sim-validated before the next begins. Money is `Decimal`/cents, never float. On uncertainty → do not trade.

---

## Phase 0: Infrastructure & Broker Selection

**Deliverables**
- Monorepo skeleton: `core/` (strategy), `api/` (FastAPI), `db/` (schema + migrations via Alembic), `dashboard/` (Next.js), `adapters/` (broker + data vendor abstraction).
- **Broker/data abstraction interface** (`BrokerAdapter`, `MarketDataAdapter`) so vendor choice is swappable and never hardcoded into strategy logic. Required methods: `submit_marketable_limit`, `partial_sell`, `cancel_all_flatten`, `subscribe_depth`, `subscribe_tape`, `get_halt_status`, `account_state`.
- PostgreSQL schema v0: `symbols`, `bars`, `quotes`, `depth_snapshots`, `tape_prints`, `signals`, `orders`, `fills`, `positions`, `ledger`, `risk_events`, `config`.
- Config service: every `⚠️ CONFLICT` parameter from the spec (C1–C16) loaded from `config` table, never literal in code. Cautious defaults per Appendix A.
- Secrets management (broker keys, data keys), structured logging, audit trail (append-only ledger), time sync (NTP; all timestamps UTC, ET derived).
- CI: lint, type-check (mypy/pyright), unit-test gate.

**Key decisions**
- **Broker for live execution** (see Broker Comparison Table). Hard requirements from spec: true depth-of-book (L2), tick time-&-sales, marketable-limit + partial sells, **no native STOP order type used** (U13), ≥7AM ET pre-market, paper environment.
- **Market-data vendor for microstructure** — most retail broker feeds are top-of-book only. The spec's iceberg/spoof/absorption logic (§2A, 13.2) needs full depth (Nasdaq TotalView-ITCH). Likely a *separate* data vendor from the execution broker.
- Account type/equity (gates PDT and cash-settlement — open client decision #2).
- Hosting/colocation: cloud VM in us-east-1 (close to NY exchanges) vs broker-adjacent. Latency budget matters for mental-stop emulation (13.4).

**Dependencies:** none (foundation).
**Complexity:** **High** — the adapter contract is the spine of the whole system; getting it wrong forces rewrites.

---

## Phase 1: Data Layer (Scanner + Market Data)

**Deliverables**
- Real-time ingest: 10-sec + 1-min OHLCV, top-of-book quotes, **full depth** stream, **tick tape** stream, LULD/halt feed, news feed.
- **Two-tier scanner** (spec §1, §9):
  - **Tier A (wide net):** gap/change ≥4%, RVOL ≥2x, float ≤50M, price $1–20.
  - **Tier B (Five Pillars trade gate):** price $2–20, float ≤20M, RVOL ≥5x, ROC ≥10%, catalyst present.
  - Sub-scanners: top-gainers, low-float top-gainer, HOD-momentum, running-up (5%/5min), halt, reverse-split/IPO, continuation.
- Reference-data resolver: **float, share count, price band** (float is the hardest field — see decision below).
- RVOL engine: rolling 50-day avg volume baseline per symbol.
- Historical data warehouse for backtest (≥2 yrs tick/L1; depth history where affordable).
- Derived indicators on stream: 9 EMA, VWAP, MACD (line/signal/histogram) on 1-min and 10-sec.

**Key decisions**
- **Depth/tape source:** Databento (TotalView-ITCH, true MBP-10/MBO, only retail-accessible full small-cap depth) vs broker-native L2 (IBKR/TradeStation, throttled/capped). Strong lean: Databento for data, broker for execution.
- **Float data source:** no clean real-time API exists; options = vendor fundamentals (Polygon/Massive, FMP, Finnhub) + SEC EDGAR share-count parsing. Float errors directly corrupt Pillar 2 → must be validated.
- SIP vs single-exchange tape: **must be SIP/consolidated** — IEX-only (≈2–4% of small-cap volume) is unusable for a momentum scanner.
- Bar construction: build own bars from tape (control over pre-market/odd-lot inclusion) vs consume vendor bars.

**Dependencies:** Phase 0 adapters + schema.
**Complexity:** **High** — full depth + tape at small-cap scale is the costliest, most failure-prone layer; the spec flags it (13.2, Appendix B).

---

## Phase 2: Strategy Engine (Signal Detection)

**Deliverables**
- Entry AND-gate E1–E7 (spec §2): universe pass, pullback (1–3 red candles, never chase vertical), candle-over-candle new high, MACD positive (hard block if red), retrace held (config `RETRACE_MAX` 0.50 / preferred 0.25), L2 support, spread ∈ [0.03, 0.10].
- **Pattern recognizers** (§4/4A), label-agnostic geometry: micro-pullback (highest conviction), ABCD (geometric P2≥P1, break of H1), bull-flag/flat-top, gap-and-go, VWAP break, red-to-green, halt resumption, reverse-split squeeze.
- Conviction scorer → feeds sizing (pattern rank, RVOL, float tier, attention rank, spread).
- Exit rule engine (§3) priority P1–P8 incl. time-stop (+10¢/60s), topping-tail, scale-into-strength, VWAP guard, re-entry rule.
- `ENTRY_TRIGGER` config: `candle_close` default, `mid_candle` only when state=HOT.
- Failed-pattern/reversal detector (universal invalidation set).

**Key decisions**
- Mid-candle vs candle-close timing (C12) — gate mid-candle behind HOT classifier (Phase 9).
- Stop basis (C5): pullback_low default vs prev-candle-low (micro).
- How "obvious"/attention is quantified (13.3) — score weight, never a hard gate.

**Dependencies:** Phase 1 (clean indicators + depth/tape). **Risk Manager (Phase 3) must exist before any engine output can route to execution.**
**Complexity:** **High** — pattern geometry is codeable, but timing conflicts and "first new high" judgment are the hard parts.

---

## Phase 3: Risk Management Layer  ⟵ BUILD BEFORE EXECUTION

**Deliverables — this is the HARD VETO GATE between strategy and execution.**
- Pre-trade veto checks (all must pass or trade is killed):
  - Five-Pillar confirm (Tier B) else `NO_TRADE_DAY` (U1).
  - 2:1 reward:risk reachable before sizing.
  - Cushion rule: `IF day_pnl <= 0 → size capped at ICEBREAKER (1/4–1/5 max)`.
  - Spread gate, liquidity cap (`LIQUIDITY_CAP = f(ADV, depth)` — never become the book).
  - PDT / cash-settlement / max-trades-per-day guard.
  - Catalyst SKIP-list block (buyout, secondary, recycled PR, pump, 5c-tick pilot).
- Live position monitors:
  - **Mental-stop emulation (U13):** internal price monitor fires **marketable-limit** on breach; **never routes a native STOP**. Optional hidden catastrophic broker stop far below as backstop only.
  - Three-strikes halt, never-average-down block, give-back stop (warn 25% / hard 50%), max-daily-loss (`min(10% acct, avg win day)`), broker hard-lockout (default $5k).
  - No-overnight flatten before close.
- Kill-switch / global flatten (`cancel_all_flatten`).
- Day-of-week + market-state size weighting hooks (Mon ×0.5; COLD caps).
- Every veto + fire logged to `risk_events` (audit).

**Key decisions**
- Max-daily-loss formula (C2) and give-back thresholds (C3) — client sign-off.
- Mental-stop latency budget vs backstop placement (13.4) — how far below.
- Sizing mode (C10): `risk_formula` default vs `flat_block`; absolute max (C11) liquidity-capped, never hardcode 100k.

**Dependencies:** Phase 0 schema. Can be developed in parallel with Phase 2 but **must be complete and tested first**.
**Complexity:** **High** — and the single most important component. Oversize/averaging-down are the recurrent blow-up causes in the spec fixtures (GLTO, ESTR, TRNR).

---

## Phase 4: Paper Trading & Backtesting

**Deliverables**
- **Backtester:** event-driven replay over historical tape/depth; reconstructs scanner → entry → risk → exit deterministically. Models slippage, partial fills, spread, ECN fees, and **mental-stop latency**.
- **Regression fixtures:** every labeled trade in spec §12 (SLXN, MLGO, GLTO, ESTR, GMBL, PALI, RKDA, GME, halt fixtures, etc.) becomes a pass/fail test — wins must trigger, losses must be vetoed.
- **Simulator (live paper):** runs full pipeline against live data, routes to paper broker, no real money.
- **Simulator gate (U6):** ≥10 consecutive sim days @ ≥60% accuracy before any live capital. Hard-enforced flag in `config`.
- Metrics: per-trade R, win rate, avg hold, give-back, max drawdown, rule-violation count (should be 0).

**Key decisions**
- Fill model realism for sub-$20 low-float (these names gap/slip hard; optimistic fills will lie).
- Depth-history availability for backtest (full L2 history is expensive; may backtest L1 + sim L2 live).
- Accuracy definition (per-trade vs per-day) for the 60% gate.

**Dependencies:** Phases 1–3 complete.
**Complexity:** **High** — realistic fill/slippage modeling for thin small-caps is where most backtests silently lie.

---

## Phase 5: Dashboard & Monitoring

**Deliverables**
- Next.js dashboard (read-mostly): live watchlist (Tier A/B), active positions, signal feed, risk-event log, day P&L vs guard thresholds, kill-switch button.
- FastAPI endpoints + WebSocket push for live state.
- Alerting: Slack/email on risk events, lockouts, disconnects, data-feed gaps.
- Health monitors: feed liveness, clock drift, order-ack latency, depth-stream staleness.
- Trade journal / post-session report (mirrors Ross's review discipline).

**Key decisions**
- How much manual override the dashboard exposes (default: kill-switch + pause only; no parameter editing mid-session to prevent emotional tampering — mirrors U11).
- Auth (single operator vs client view).

**Dependencies:** Phases 1–4 (needs real state to display).
**Complexity:** **Medium** — standard web stack; criticality is in the monitoring/alerting, not the UI.

---

## Phase 6: Live Trading

**Deliverables**
- Live broker adapter hardened: real marketable-limit + partial sells + cancel-all-flatten, reconciliation against broker positions every loop.
- Staged capital ramp: micro size → starter cap → full, gated by realized cushion (spec §5/§6).
- Idempotent order handling (no duplicate fills on retry), disconnect/recovery (on feed loss → flatten or freeze, never trade blind).
- Pre-market readiness checklist automation (account type, buying power, data feeds, halt feed, clock).
- Live runbook + incident playbook.

**Key decisions**
- Go-live capital and `BROKER_HARD_LOCKOUT` value (client).
- Behavior on partial data outage: flatten-and-halt vs hold-and-freeze.
- Production broker final selection vs paper broker (may differ — Alpaca paper, IBKR/TradeStation live).

**Dependencies:** **All prior phases + passed simulator gate (U6).** No exceptions.
**Complexity:** **High** — real money, real latency, real regulatory exposure.

---

## Phase 7: Catalyst Detection (Automation Note 13.1)

**Deliverables:** NLP classifier over real-time news (FDA/M&A/offering/contract/theme tagging); reaction-proof gate (`≥10% AND ≥5x RVOL`); hard-block SKIP categories via keyword + SEC filing check (S-1/S-3/424B dilution, 13D/13G, Form 4).
**Key decisions:** news vendor (Benzinga Pro vs equivalent) + EDGAR/BAMSEC integration; classifier confidence threshold (bias to **skip** on ambiguity — false negative is safe).
**Dependencies:** Phase 1 (news feed), Phase 3 (SKIP enforcement).
**Complexity:** **High** — semantic, proprietary "flame" flag; recurrent loss source if wrong (PALI/PTPI).

## Phase 8: Level 2 / Tape Microstructure Engine (13.2)

**Deliverables:** real floor vs spoof detector, iceberg detector (executed ≫ displayed-ask with no price advance), green-tape rate, absorption/break trigger (E6), exit signal P3. Require **prints-confirmation** before E6 fires.
**Key decisions:** full-depth feed (Databento TotalView) confirmed; heuristic thresholds per symbol liquidity; latency tolerance.
**Dependencies:** Phase 1 (depth+tape), Phase 2 (entry gate consumes E6/E7).
**Complexity:** **High** — spoof-as-floor and iceberg-as-breakout are direct fixture losses (CADL, GMBL, NIXX).

## Phase 9: Market-State Classifier — HOT/COLD/REHAB (13.9) + Attention (13.3)

**Deliverables:** rolling-feature classifier (gapper follow-through %, breakout success %, avg green/red day size, count of >100%/<5M-float names) → HOT/COLD/REHAB; %-gain rank + RVOL percentile + mention velocity for "obvious".
**Key decisions:** feature windows + thresholds; **bias COLD on uncertainty** (gates EX1/EX2/mid-candle/oversize).
**Dependencies:** Phase 1 (scanner stats), Phase 4 (own trade ledger).
**Complexity:** **High** — gestalt judgment; a HOT misread in cold tape enables jackknife losses.

## Phase 10: Execution Safety — Mental Stops & Time Stop (13.4, 13.5)

**Deliverables:** low-latency internal monitor firing marketable-limit on breach (no native STOP); quantified breakout-or-bailout (`unrealized < +0.10 at T+60s AND no higher-highs on rising volume → flatten`); hidden catastrophic backstop.
**Key decisions:** loop latency budget; `BAILOUT_SECONDS`/`BAILOUT_MOVE` tuning per regime (backtested).
**Dependencies:** Phase 3 (risk monitors), Phase 6 (live order path).
**Complexity:** **High** — latency → worse fills than a resting stop; must be measured, not assumed.

## Phase 11: Halt Resumption & Multi-Day Continuation (13.7, 13.10)

**Deliverables:** halt engine (default `post_halt`; consume LULD + reopen auction; enter only if resume ≥ prior price with green prints; **hard-block halt-down** unless VWAP reclaimed — EX5); continuation engine (eligibility Day-1 ≥100% & held close; done-conditions numeric; auto-switch to 5-min + reduced size).
**Key decisions:** broker that trades the reopen + exposes imbalance/resumption quotes (many retail hide it); continuation eligibility %.
**Dependencies:** Phase 1 (halt feed), Phase 8 (tape confirm), Phase 9 (size by state).
**Complexity:** **High** — buying a halt-down resumption is an immediate loss (EX5).

## Phase 12: Sizing/Liquidity & Pattern Hardening (13.6, 13.8)

**Deliverables:** `risk_formula` ($1k/stop) default clamped by `LIQUIDITY_CAP = f(ADV, depth)`; cap order at % of top-N-level depth; pattern engine hardened for "first new high" timing + ABCD label-agnostic geometry; mid-candle gated to HOT.
**Key decisions:** depth-% cap fraction; per-regime bailout tuning.
**Dependencies:** Phase 2, Phase 3, Phase 8, Phase 9.
**Complexity:** **Medium-High** — oversize → self-slippage (TRNR/ESTR); the cap is the mitigation.

## Phase 13: Regulatory / Account Compliance (13.11)

**Deliverables:** startup hard-gate confirming account type/equity; PDT guard (<$25k → ≤3 day-trades/5 days); cash-settlement T+1 → one-trade-per-day; wash-sale tracking on high-frequency re-entries; SSR/LULD awareness in halt logic.
**Key decisions:** account structure (client decision #2); whether shorting is ever in scope (currently out → locate/HTB deferred).
**Dependencies:** Phase 0 (account state), Phase 3 (trade-count guard).
**Complexity:** **Medium** — mostly deterministic rules, but a PDT violation freezes the account, so it must hard-gate before any small-account mode.

---

## Broker Comparison Table

Criteria scored against the spec's hard requirements. Pricing/specs verified against 2026 vendor docs.

| Broker | Pre-market access | API quality | Level 2 (true depth) | Low-float small-cap | Paper trading | Commission |
|---|---|---|---|---|---|---|
| **Interactive Brokers (IBKR)** | Yes, from 4:00 AM ET | Strong, multi-asset; TWS/Web API; session-based (Gateway must run), steep curve | **Yes** via TotalView/ArcaBook, **but throttled** (~0.1s depth snapshots; deep-book windows capped ~3 symbols at default 100 data lines) | Excellent; broadest universe incl. thin names | Yes (demo cannot subscribe to live data) | Tiered/fixed, low; ECN/regulatory pass-through |
| **TradeStation** | Yes (pre/post) | Good; REST + FIX WebAPI, sandbox; **L2 TotalView on WebAPI** since 2023 | **Yes** — API users can build TotalView depth tools | Good; self-clearing equities | Yes (sandbox) | $0 stocks; $10k min balance to get API key |
| **Alpaca** | Yes, from 4:00 AM ET | **Excellent** dev-first REST/WebSocket; best Python SDK; cleanest paper API | **No native depth-of-book** — SIP top-of-book quotes + trades only (must bring own L2) | Listed US equities; **no OTC/pink** | **Yes — best-in-class paper API** | $0 commission (regulatory fees apply) |
| **Tradier** | Yes (pre/post durations) | API-first, clean REST; **~320ms avg execution — too slow for HFT-speed scalps** | **No** — quotes only, no depth | Equities/options; **no OTC/Pink Sheets** | Sandbox (15-min delayed data) | $0 sub or $10/mo flat; per-contract options |
| **Webull** | Yes | Official OpenAPI (Python/Java; HTTP/gRPC/MQTT), newer/less battle-tested | Limited; not a true API depth product for this use | Listed US equities | Yes (test env) | $0 commission |
| **Hyperliquid** | ❌ N/A | (crypto perps DEX) | N/A | ❌ **Does not trade US equities** | N/A | N/A |
| **Cryptohopper** | ❌ N/A | (crypto trading-bot SaaS) | N/A | ❌ **Does not trade US equities** | N/A | N/A |

**Unlisted but relevant (flagged proactively):**
- **Databento** — *data vendor, not a broker.* Exchange-direct **Nasdaq TotalView-ITCH (MBP-10/MBO)** — the only retail-accessible source of true full-depth + tick tape on small caps. Metered (~$100–500/mo by universe). **Strongly recommended as the microstructure data layer** regardless of execution broker.
- **Polygon.io (now "Massive")** — SIP tape/bars, flat ~$199/mo Advanced; great for scanner/bars/backtest, **not full depth**.
- **DAS Trader / CenterPoint / Lightspeed / Cobra** — the direct-access platforms Ross-style traders actually use (fast hotkeys, real short locates). APIs are limited/unofficial; relevant only if you later need short-locate (out of scope now).

**Recommendation (2–3 approaches with trade-offs):**

1. **Alpaca (paper + early execution) + Databento (depth/tape).** *Pros:* best dev velocity, best paper API, best microstructure data, cheapest to start. *Cons:* two vendors; Alpaca has no native depth so the L2 engine fully depends on Databento; Alpaca execution quality for thin names is unproven for this style.
2. **IBKR (execution + L2) + Databento (clean depth/tape).** *Pros:* one robust broker covering the whole universe with low cost; Databento removes IBKR's depth throttling problem. *Cons:* steep API, Gateway session management, market-data-line limits.
3. **TradeStation (execution + native WebAPI L2).** *Pros:* single vendor with REST/FIX + TotalView depth + sandbox; self-clearing small-caps. *Cons:* $10k API minimum; smaller ecosystem; depth quality for the spec's iceberg logic needs validation.

**Recommended path:** Build the **vendor-agnostic adapter (Phase 0)**, develop Phases 0–5 on **Alpaca paper + Databento data** (fastest + best data, lowest cost), then go live on **IBKR or TradeStation** with Databento retained as the depth/tape source. This decouples "best dev/paper" from "best live execution" and avoids lock-in. **Final live broker is an open client decision** (gated by client decision #1 data/broker vendor and #2 account type).

---

## Tech Stack Decision

- **Python 3.11+ (core/strategy/risk):** dominant quant/trading ecosystem (pandas, numpy, polars, ta-libs, alpaca-py, ib_insync, databento client). Fast enough for second-scale logic; the latency-critical mental-stop loop is simple and can be tightened or dropped to a compiled path if measured latency demands. Async (`asyncio`) for concurrent feed handling.
- **FastAPI (backend API):** async-native (matches WebSocket data/order streams), Pydantic validation (enforces typed money/config models), auto OpenAPI docs, minimal overhead. Cleanly separates the trading core from the dashboard.
- **PostgreSQL (data/ledger):** ACID is mandatory for an order ledger and audit trail; strong typing (`NUMERIC` for money — never float), partitioning for high-volume `bars`/`tape`, mature tooling. Add **TimescaleDB** extension for time-series bars/quotes/depth if volume warrants. Append-only `ledger`/`risk_events` for auditability.
- **Next.js (dashboard):** SSR + WebSocket-friendly, fast to build a read-mostly monitoring UI; only needed once live state exists (Phase 5). Kept deliberately thin — monitoring + kill-switch, not a trading terminal.
- **Cross-cutting:** Alembic (migrations), Redis (hot in-memory state / pub-sub for live signals), Docker (reproducible deploy), pytest (fixtures = spec §12), mypy/pyright (types). Host in **us-east-1** to minimize exchange round-trip latency.

Each choice maps to a hard constraint: ACID ledger (Postgres), async streams (FastAPI/asyncio), ecosystem + speed-to-build (Python), thin safe monitoring (Next.js).

---

## Risk & Legal Flags

**Could kill it legally**
- **PDT rule:** <$25k equity → ≤3 day-trades/5 days. A day-trading bot violates this instantly on a small account → account freeze. Must hard-gate at startup (Phase 13). **Blocks production until account equity confirmed (open client decision #2).**
- **Cash-account settlement (T+1):** unsettled-funds violations / good-faith violations → restrictions. Forces one-trade-per-day in cash mode.
- **Pattern-day-trader, wash-sale, and market-manipulation exposure:** high-frequency re-entries trigger wash sales (tax/reporting); never place orders that could resemble spoofing/layering.
- **Automated-trading & market-data licensing:** redistribution/display licensing on TotalView and vendor feeds; "non-professional" vs "professional" data status affects fees and legality of automated use. Confirm per vendor.
- **Regulatory status of the operator:** running an automated strategy for a *paying client* may implicate investment-adviser / managed-account rules depending on structure. **Get legal review before live client money.**
- **Trading on material news via NLP:** ensure no use of non-public data; catalyst feed must be licensed public news.

**Could kill it technically**
- **Depth/tape data gap:** the spec's entire L2 edge (iceberg/spoof/absorption) depends on true full depth most retail APIs don't provide. If Databento (or equivalent) isn't in the stack, E6/E7 and exit P3 degrade to guesswork. **Single biggest technical risk (Appendix B).**
- **Float data accuracy:** Pillar 2 hinges on float; there is no clean real-time float API. Bad float → wrong universe → wrong trades.
- **Mental-stop latency (U13):** forbidding resting stops means a software monitor must fire fast; latency → materially worse fills than a stop would have given. Must be measured; backstop required.
- **Backtest fidelity on thin small-caps:** optimistic fill/slippage modeling will overstate edge and produce a bot that loses live. The §12 fixtures + conservative fill model are the guard.
- **Halt/reopen handling:** mis-trading a halt-down resumption (EX5) is an instant loss; needs imbalance/resumption quotes many brokers hide.
- **Disconnect/partial-outage behavior:** trading blind on a stale feed is catastrophic → default flatten-and-freeze.

**Could kill it financially**
- **Oversize / become-the-book slippage:** the recurrent blow-up cause in the spec (GLTO, ESTR, TRNR). `LIQUIDITY_CAP` on every order is non-negotiable.
- **Strategy decay / regime mismatch:** a strategy tuned to HOT markets bleeds in COLD tape; the market-state classifier must bias COLD and gate aggression.
- **Data + execution cost:** TotalView depth + tick tape + news feeds are the major recurring cost; model it against expected edge before scaling.
- **Catalyst traps:** buyout/secondary/recycled-PR names (U15) pin price or dilute — auto-skip list must hold.

**Hard gates before any live capital:** (1) simulator gate U6 passed (≥10 sim days @ ≥60%); (2) account type/equity confirmed and PDT/cash rules enforced; (3) legal review of client-money structure; (4) full-depth data feed live and validated; (5) kill-switch + disconnect-flatten tested.

**Two open client decisions still blocking production:** (1) **data/broker vendor** — gates whether L2 depth + tick tape + halt imbalance quotes are actually available; (2) **account type/equity** — gates PDT and cash-settlement behavior.