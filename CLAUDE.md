# CLAUDE.md — RossBot

> Read this file in full at the start of EVERY session before writing or changing code.
> It is the persistent contract for this project. If anything here conflicts with a
> one-off instruction in chat, surface the conflict instead of silently picking one.

---

## 0. What this project is

**RossBot** is a production automated US-equities day-trading bot that replicates the
day-trading strategy of **Ross Cameron (DaytradeWarrior)**. It scans the market, identifies
the setups Ross would trade, and executes them under strict risk controls.

- **Client:** a paying US client. This is real money, real markets, real consequences.
- **Strategy source:** EXCLUSIVELY Ross Cameron's ~1,750 YouTube videos, distilled into the
  master spec. Do NOT invent strategy, import outside trading ideas, or "improve" the edge.
  If the spec doesn't say it, it isn't in scope.
- **End goal:** a bot that scans → identifies Ross-style setups → executes → manages risk,
  matching the spec's behavior and passing the regression fixtures.

## 1. Source of truth

**`ROSSBOT_STRATEGY_SPEC.md` (currently V2.0) is the single authoritative strategy spec.**
**`ROSSBOT_PROJECT_PLAN.md` is the single authoritative Project plan to be followed strictly.**
- Every strategy/risk/execution rule in code MUST trace to a section of the spec. Cite the
  section in code comments (e.g. `# spec §3 P2 breakout-or-bailout`).
- If you find a strategy question the spec doesn't answer, do NOT guess. Stop, flag it, and
  ask. Add it to the spec's Appendix A (open conflicts) if it's a genuine ambiguity.
- When the spec changes, code follows. When code must diverge from the spec, the spec is
  updated first (or in the same change) — never let them drift apart.
- Conflicts in the spec are marked `⚠️ CONFLICT`. These resolve to **config**, never to a
  hardcoded pick. See §6 below.

## 2. Tech stack (fixed direction)

| Layer | Choice |
|---|---|
| Core bot / strategy engine | **Python** (3.11+) |
| Backend / API | **FastAPI** |
| Persistence | **PostgreSQL** (trades, ledger, daily state, config, audit) |
| Dashboard (if/when needed) | **Next.js** |
| Config | typed config (pydantic settings); every spec ⚠️ value is a config key |

Don't introduce new languages/frameworks without flagging it first. Keep dependencies lean.

## 3. Target architecture (high level — detailed plan is the next deliverable)

```
            ┌────────────┐   market data + news + L2/tape + halt feed
            │  DATA FEED │◄──────────────────────────────────────────
            └─────┬──────┘
                  ▼
 ┌──────────┐  Tier A wide net → Tier B Five Pillars
 │ SCANNER  │  (spec §1, §9)
 └────┬─────┘
      ▼ candidates
 ┌──────────────┐  entry conditions E1–E7, patterns §4/§4A, L2 §2A
 │ STRATEGY     │  catalyst classify §1, market-state §8
 │ ENGINE       │
 └────┬─────────┘
      ▼ proposed trade
 ┌──────────────┐  ★ HARD GATE — can VETO any trade ★
 │ RISK MANAGER │  sizing §6, cushion/3-strikes/give-back/daily-loss §5,
 │              │  PDT/cash §13.11, no-live-stops §3 U13
 └────┬─────────┘
      ▼ approved order
 ┌──────────────┐  limit-only + offset §10, mental-stop monitor,
 │ EXECUTION    │  scale-outs, marketable-limit on stop breach
 └──────────────┘
      ▼
 ┌──────────────┐  every decision + fill + reason logged
 │ LEDGER/AUDIT │  PostgreSQL; feeds market-state classifier + reviews
 └──────────────┘
```

Design so the **Risk Manager sits between Strategy and Execution as a mandatory gate**. No
order reaches the broker without passing it. Strategy proposes; Risk disposes; Execution obeys.

## 4. NON-NEGOTIABLE guardrails (hardcode; no config override in prod)

These map to spec §11 (U1–U15). Enforce in the Risk Manager / Execution layer. A violation
should be impossible by construction, not just discouraged.

- **U1** No Five-Pillar (Tier B) symbol → NO-TRADE day. Don't force trades.
- **U2** Never average down. Adding to a red position is forbidden.
- **U3** No overnight holds. Flat before close, every day.
- **U4** Daily stop: `day_pnl <= -MAX_DAILY_LOSS` OR 50% peak give-back → shut down trading.
- **U5** 3 consecutive losses → halt for the day.
- **U6** Simulator-first: a strategy goes live only after ≥10 consecutive sim days @ ≥60%
  accuracy. The live/sim switch is a hard gate.
- **U7** Limit orders only. **Never market orders.** Buy @ ask+offset, sell @ bid.
- **U8** No counter-trend: no bottom-fishing crashes, never short a stock making new highs.
- **U9** No illiquid trades (clamp by `LIQUIDITY_CAP`; never be the whole book).
- **U13** **No resting stop orders.** Market makers hunt visible stops. Stops are MENTAL:
  monitor price internally and fire a **marketable-limit** on breach. Do NOT route a native
  STOP/STOP-LIMIT order type. (Optional hidden catastrophic backstop far below mental level.)
- **U14** Never anticipate a $0.50/$1.00 break when a hidden seller is present.
- **U15** Never trade buyout / secondary-offering / recycled-PR catalysts (spec §1 SKIP list).

> **Risk management is never optional and never skipped.** If a feature would weaken a
> guardrail "for now," don't build it that way — ask first.

## 5. Hard rules consistent across all sources (build as-is)

- Five Pillars gate (price $2–20, float ≤20M, RVOL ≥5x, ROC ≥10%, catalyst) — spec §1.
- Entry is an AND-gate of E1–E7 — spec §2. Never a partial match.
- MACD must be positive/crossing-up; hard-block on red MACD.
- 2:1 minimum reward:risk before a trade qualifies.
- Cushion rule: while `day_pnl <= 0`, size is capped at icebreaker (¼–⅕ max).
- Primary window 07:00–10:00 ET; no new entries after hard-stop time (default 11:00).

## 6. Conflicts → config (never hardcode a pick)

Every `⚠️ CONFLICT` in the spec is a config key with the spec's proposed default. The full
list is **Appendix A (C1–C16)**. Critical ones to wire early:

- `SIZING_MODE = {risk_formula | flat_block}` (default risk_formula) — C10
- `MAX_SIZE` + `LIQUIDITY_CAP` (never hardcode 100k) — C11
- `ENTRY_TRIGGER = {candle_close | mid_candle}` (default candle_close; mid only in HOT) — C12
- `CATALYST_VERIFY_MODE = {before | after}` (default before; after only in HOT) — C13
- `HALT_MODE = {pre_halt | post_halt}` (default post_halt) — C14
- `RETRACE_MAX` 0.50 / `RETRACE_PREFERRED` 0.25 — C9
- `MAX_DAILY_LOSS`, `GIVE_BACK_WARN/HARD`, `MOVE_BE_TRIGGER`, `SCAN_START`, `HARD_STOP_TIME`

Defaults bias toward **caution** (the cold-market read). When market state is uncertain,
classify COLD.

## 7. Highest-risk dependencies (architect honestly around these)

1. **Catalyst detection (Pillar 5, spec §13.1)** — semantic, hardest to automate. Needs a
   real-time news feed + NLP classifier + the reaction-proof gate + SEC-filing dilution check.
   Bias the classifier toward **skip** on ambiguity (false-negative = no trade = safe).
2. **Level 2 / tape / halt imbalance (§2A, §12A, §13.2)** — needs true depth-of-book + tick
   tape + resumption quotes. **Most retail APIs can't provide this.** Confirm the data vendor
   before building L2 logic; if unavailable, that logic is blocked, not faked.
3. **Mental-stop emulation (§13.4)** — internal monitor + marketable-limit; latency-sensitive.
4. **Liquidity-aware sizing (§13.6)** — oversize is the recurrent blow-up cause in the
   fixtures (ESTR/TRNR/GLTO). Clamp every order by depth.
5. **Market-state classifier (§13.9)** — gates the risky exceptions (EX1/EX2/mid-candle/
   oversize). A wrong HOT read in a cold tape is how losses happen. Bias COLD.

## 8. Open client decisions that block production (don't proceed past them silently)

- **Data/broker vendor** — determines whether L2 depth, tick tape, and halt imbalance quotes
  are even available (gates §2A and §12A). Also whether the broker supports marketable-limit
  + partial sells and exposes the reopen auction.
- **Account type + equity** — PDT (<$25k → ≤3 day-trades/5 days) and cash-settlement
  (T+1 → one-trade-per-day) change trade-count rules at startup (§13.11). Hard-gate at boot.

## 9. Testing & validation (required, not optional)

- **Regression fixtures:** the labeled trade examples in spec §12 (SLXN, MLGO, GLTO, ESTR,
  GMBL, PALI, PTPI, RBLX, RKDA, NIXX, TIX, GME, TRNR, INHD, halt names…) are test cases.
  Wins must trigger entries; losses must be avoided/cut for the documented reason. New
  strategy code must run against these.
- **Simulator gate (U6):** no live capital until the ≥10-day/≥60% bar is met in sim.
- **Risk-gate tests first:** before any "make money" feature, the daily-loss, 3-strikes,
  give-back, cushion, no-average-down, and no-overnight gates must be tested and proven to
  veto correctly. Test the brakes before the engine.
- Deterministic where possible; seed/replay market data for repeatable backtests.

## 10. Coding conventions

- Python: type hints everywhere, pydantic models for data + config, `ruff`/`black`, pytest.
- Pure functions for strategy logic (input bars/quotes → signal) so they're unit-testable.
- No side effects in the strategy layer; only the Execution layer talks to the broker.
- Every order and every veto writes an auditable row (symbol, time, reason, spec ref).
- Money = integer cents or `Decimal`, never float. No float for prices, PnL, or sizing.
- Fail safe: on any uncertainty, ambiguous data, or feed gap → do NOT trade.
- Time is ET, market-aware; handle pre-market, RTH, halts, and DST correctly.

## 11. Working discipline (how you, Claude Code, operate on this project)

1. **Start of session:** read this file + skim `ROSSBOT_STRATEGY_SPEC.md`. Confirm which phase
   you're in.
2. **Stay on the goal:** every change should move toward "scan → identify Ross setup →
   execute → manage risk." If a task drifts from that, say so.
3. **Keep docs in sync:** if you change behavior, update the spec and this file in the same
   change. Don't let the three (code/spec/CLAUDE.md) diverge.
4. **Update memory / project log:** maintain a short running `PROGRESS.md` (or the project memory)
   noting what was built, decisions made, open questions, and the next step. Update it at the
   end of each working session so the next session has continuity.
4. **Update Changelog.md file:** On every change on the code always update the chagelog file.
6. **Propose before big moves:** for any significant architectural or dependency choice, give
   2–3 options with trade-offs and a recommendation before implementing.
7. **Never skip risk management.** If you're tempted to ship a strategy feature before its
   risk gate exists, stop and build the gate first.
8. **Don't expand scope:** no extra indicators, markets, asset classes, or "smart" overrides
   that aren't in the spec.
9. **Push code to github:** On every code change, always push the code to github repo https://github.com/prashantchawla3/Rossbot-AI-trader.git with standard understandable commits.

## 12. Phase roadmap (placeholder — the detailed build plan is the next deliverable)

1. Project skeleton, config system, PostgreSQL schema, broker/data adapters (interfaces).
2. Scanner (Tier A → Tier B Five Pillars).
3. Risk Manager gate (guardrails U1–U15) + sizing — **before** execution.
4. Strategy engine (entries E1–E7, patterns §4A, catalyst classifier, market-state).
5. Execution layer (limit+offset, mental-stop monitor, scale-outs).
6. Backtest harness + regression fixtures + simulator gate.
7. Dashboard (Next.js) if/when needed.

> Build the risk gate before the money-making path. Brakes before engine.

---
**Remember:** real money, real client, strategy strictly from the spec, risk first, docs in
sync, memory updated every session, and when in doubt — don't trade, and ask.