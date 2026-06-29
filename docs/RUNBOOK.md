# RUNBOOK.md — RossBot Live Trading

> Phase 6 live runbook and incident playbook.
> Real money is in play whenever `LIVE_ENABLED=true`. Read this file in full before each live session.
> Source of truth for strategy rules: `ROSSBOT_STRATEGY_SPEC.md` v2.0
> Guardian gates: `CLAUDE.md` §4 (U1–U15)

---

## 1. Pre-Market Readiness Checklist

Run `ReadinessChecker.check_all()` (via the CLI or the dashboard `/health/ready` endpoint) before the 7:00 AM ET scan window opens. All 8 items must pass before any order is submitted.

| # | Check | Requirement | Block on fail? |
|---|---|---|---|
| 1 | `LIVE_ENABLED` | Config key must be `true` | **Hard block** |
| 2 | `U6_GATE` | ≥10 consecutive sim days @ ≥60% accuracy | **Hard block** |
| 3 | `ACCOUNT_TYPE` | Must be MARGIN or CASH (not UNKNOWN) | **Hard block** |
| 4 | `BUYING_POWER` | ≥ `READINESS_MIN_BUYING_POWER` (default $5,000) | **Hard block** |
| 5 | `PDT_EQUITY` | Advisory: warns if margin account < $25k | Warning only |
| 6 | `CAPITAL_TIER` | `CAPITAL_RAMP_TIER` must be MICRO, STARTER, or FULL | **Hard block** |
| 7 | `CLOCK_DRIFT` | NTP drift < `CLOCK_DRIFT_MAX_MS` (default 500 ms) | **Hard block** |
| 8 | `DATA_FEED` | SPY quote probe must return within 10 s | **Hard block** |

### How to run the readiness check

```bash
# Via API (FastAPI must be running)
curl http://localhost:8000/health/ready

# Via Python (standalone)
python -c "
import asyncio
from core.config import load_config
from core.backtest.sim_gate import SimulatorGate
from core.live.readiness import ReadinessChecker
from adapters.alpaca_broker import AlpacaBrokerAdapter
from adapters.alpaca_data import AlpacaDataAdapter

cfg = load_config()
gate = SimulatorGate.load_from_db(cfg)   # or inject from DB
broker = AlpacaBrokerAdapter(cfg)
data = AlpacaDataAdapter(cfg)
checker = ReadinessChecker(cfg, gate, broker, data)
result = asyncio.run(checker.check_all())
print(result.summary())
if not result.all_passed:
    raise SystemExit(1)
"
```

---

## 2. Capital Ramp Tiers

Capital ramp is set **at session start** from `CAPITAL_RAMP_TIER`. Never change it mid-session (U11).

| Tier | Max shares per trade | When to use |
|---|---|---|
| `MICRO` | `CAPITAL_RAMP_MICRO_SHARES` (default 100) | First live days; hardware/software checkout |
| `STARTER` | `CAPITAL_RAMP_STARTER_SHARES` (default 2,000) | After 5+ profitable MICRO sessions |
| `FULL` | No ramp cap (Risk Manager sizing rules only) | After 10+ profitable STARTER sessions |

To promote a tier: update `CAPITAL_RAMP_TIER` in the DB config table, then restart the session. Never promote mid-session.

Ramp promotion criteria (per spec §5/§6):
1. Previous tier has ≥ 5 sessions of net-positive P&L (confirmed in the ledger)
2. No rule violations or U-gate breaches in the tier's history
3. Client sign-off recorded in PROGRESS.md

---

## 3. Daily Session Startup

```
07:00 ET — Scan window opens
  1. Confirm readiness check is green (all 8 items pass)
  2. Confirm `CAPITAL_RAMP_TIER` is correct for today's session
  3. Confirm broker positions = 0 (start flat)
  4. Confirm reconcile log is clean (no ghost/orphan positions from prior session)
  5. Note today's account equity and buying power
  6. Set `LIVE_ENABLED=true` in config ONLY if all above pass

07:00–10:00 ET — Primary trading window
  - Scanner runs Tier A → Tier B Five Pillars
  - Strategy Engine emits signals
  - Risk Manager is the mandatory gate (every proposed trade passes through it)
  - LiveSession reconciles broker positions every RECONCILE_INTERVAL_S (default 30 s)
  - Mental-stop monitor polls every LIVE_POLL_MS (default 100 ms)

10:00 ET — End of primary window (no new entries after HARD_STOP_TIME = 11:00)
11:00 ET — Hard stop: no new entries permitted (spec §7)

EOD_FLATTEN_TIME (default 15:55 ET) — All positions flattened automatically
  - LiveSession._eod_flatten_loop fires cancel_all_flatten()
  - Verify flat in dashboard before market close
  - Review day's journal: P&L, fills, risk events, any U-gate breaches
```

---

## 4. Order Routing Rules (enforced by construction)

| Rule | Implementation | Spec ref |
|---|---|---|
| Limit orders only | `submit_marketable_limit` → Alpaca limit @ ask+offset | U7 |
| No native STOP orders | Mental-stop monitor fires `partial_sell` (limit @ bid) on breach | U13 |
| No market orders | Only exception: `cancel_all_flatten` kill-switch (emergency only) | U7 exception |
| Buy offset | `BUY_OFFSET` config key (default $0.05) | spec §10 |
| Sell at bid | `partial_sell` always uses current bid price | spec §10 |
| Idempotent orders | Duplicate `client_order_id` → fetch existing order, no double fill | Phase 6 |

---

## 5. Incident Playbook

### INCIDENT 1: Readiness check fails at startup

**Symptoms:** `/health/ready` returns 503; `ReadinessResult.all_passed = False`.

**Response:**
1. Read `result.failed_names()` to identify which checks failed.
2. If `U6_GATE`: do not trade live. Return to simulation. Log in PROGRESS.md.
3. If `DATA_FEED`: check Alpaca subscription status (Algo Trader Plus required for SIP). Restart data adapter.
4. If `CLOCK_DRIFT`: sync system clock (NTP server), then retry.
5. If `BUYING_POWER`: check account for margin calls or pending withdrawals.
6. **Do not override `skip_readiness=True` in production.** That flag is for tests only.
7. Log the failed items and reason in PROGRESS.md before any retry.

---

### INCIDENT 2: Position reconciliation discrepancy

**Symptoms:** Reconcile log shows `broker_only`, `internal_only`, or `qty_mismatch` entries.

**Definitions:**
- `broker_only` (ghost): Broker has a position that RossBot does not track → potential duplicate order.
- `internal_only` (orphan): RossBot tracks a position that broker does not confirm → state is stale.
- `qty_mismatch`: Both sides agree on the symbol but quantities differ.

**Response:**
1. **Halt new entries immediately.** Call `POST /controls/pause` or `session.stop()`.
2. Log the discrepancy with symbol, broker qty, internal qty, timestamp.
3. For **ghost positions**: do NOT enter a conflicting position. Manually verify the broker fill in the Alpaca dashboard. If the ghost is real, risk-manage it manually.
4. For **orphan positions**: the internal state is wrong. Remove the orphan from `_open` (automatic via `_reconcile_loop`). Verify broker shows 0 for that symbol.
5. For **qty mismatch**: trust the broker. Adjust internal state or close the position manually to re-sync.
6. Resume only after `reconcile_positions(broker, internal).clean == True`.
7. Log the root cause in PROGRESS.md.

---

### INCIDENT 3: Data feed staleness / feed watchdog fires

**Symptoms:** `_feed_watchdog_loop` detects `_last_bar_ts` staleness > `FEED_STALENESS_SECONDS` threshold.

**Response (automatic):**
1. `_frozen = True` is set → no new entry signals are processed.
2. `_handle_disconnect()` is called → attempts `cancel_all_flatten()` up to `RECONNECT_MAX_ATTEMPTS` times.

**If broker is reachable:** Positions are flattened and `_open` is cleared. Session is safe. Investigate feed.
**If broker is unreachable:** Positions remain open but `_frozen = True` blocks new entries. A CRITICAL alert is logged.

**Manual response (broker unreachable):**
1. Log in PROGRESS.md: timestamp, positions held, reason broker was unreachable.
2. Open Alpaca dashboard immediately: manually verify and close all open positions.
3. Do not restart the bot until broker connectivity is confirmed and positions are flat.
4. Root cause the feed outage (Alpaca status page, network connectivity, API key expiry).

---

### INCIDENT 4: Daily loss limit or 3-strikes halt fires

**Symptoms:** `RiskManager.halted == True`; new entry signals all return `TradeApproval(approved=False, vetoes=[VetoReason.HALTED])`.

**Response:**
1. This is correct behavior (U4 / U5). Do not override the halt.
2. Verify in the dashboard: P&L, risk events, which strike triggered the halt.
3. Review the three losing trades. Did each loss have a valid entry signal? Did the exit happen at the mental stop?
4. Log the day's outcome in PROGRESS.md (fill prices, reasons, any spec-rule violations).
5. The halt resets automatically at next session via `RiskManager.reset_session()`.
6. Do not manually call `halt_session(False)` to un-halt mid-session. Walk away (U11).

---

### INCIDENT 5: Kill-switch activation

**Symptoms:** `POST /controls/kill-switch` called; `cancel_all_flatten()` is dispatched.

**Response:**
1. This sends Alpaca `close_all_positions(cancel_orders=True)` — market orders internally (emergency exception to U7).
2. Verify in Alpaca dashboard that all positions are closed and all open orders are cancelled.
3. Do not restart until root cause is understood.
4. Log in PROGRESS.md: time, reason for kill-switch, positions at time of activation, fills.

---

### INCIDENT 6: Duplicate fill / idempotency failure

**Symptoms:** Two fills with the same or nearly identical `client_order_id`; more shares than expected in a position.

**Response:**
1. Halt new entries immediately.
2. Log both fills (order IDs, timestamps, quantities, prices) in PROGRESS.md.
3. Reconcile broker position against internal state: close the excess manually.
4. Root cause: check whether the adapter correctly caught the 422 duplicate error and fetched the existing order instead of creating a new one.
5. If the Alpaca adapter is returning duplicate `client_order_id` errors without falling back to `get_order_by_id`, escalate to code review before resuming.

---

### INCIDENT 7: Overnight hold (U3 breach)

**Symptoms:** `_open` contains positions after `EOD_FLATTEN_TIME`; U3 violation alert fires.

**Response:**
1. This must not happen by construction. If it does, manually close all positions via Alpaca dashboard immediately.
2. Investigate why `_eod_flatten_loop` did not fire:
   - Was `should_flatten_eod()` returning `False`? Check `EOD_FLATTEN_TIME` config vs current ET time.
   - Was `cancel_all_flatten()` called but failing silently?
3. Log the breach in PROGRESS.md with positions, time, reason.
4. Do not accept overnight P&L as a "win." Spec §11 U3 is absolute.
5. The broker will carry the position overnight if not closed. Close before next session opens.

---

## 6. Config Keys Reference (Phase 6)

| Key | Default | Description | Spec ref |
|---|---|---|---|
| `LIVE_ENABLED` | `false` | Hard gate — must be `true` to enter LiveSession.run() | U6 |
| `LIVE_POLL_MS` | `100` | Mental-stop monitor poll interval in milliseconds | §13.4 |
| `RECONCILE_INTERVAL_S` | `30` | Seconds between broker position reconcile | Phase 6 |
| `RECONNECT_MAX_ATTEMPTS` | `3` | Max retries for cancel_all_flatten on disconnect | Phase 6 |
| `RECONNECT_DELAY_S` | `5` | Seconds between reconnect attempts | Phase 6 |
| `CAPITAL_RAMP_TIER` | `MICRO` | Active capital tier: MICRO / STARTER / FULL | §5/§6 |
| `CAPITAL_RAMP_MICRO_SHARES` | `100` | Max shares per trade in MICRO tier | §5/§6 |
| `CAPITAL_RAMP_STARTER_SHARES` | `2000` | Max shares per trade in STARTER tier | §5/§6 |
| `READINESS_MIN_BUYING_POWER` | `5000.00` | Minimum buying power required to go live | Phase 6 |
| `READINESS_MIN_EQUITY` | `25000.00` | Advisory PDT equity threshold (margin accounts) | §13.11 |
| `CLOCK_DRIFT_MAX_MS` | `500` | Maximum acceptable NTP clock drift in ms | Phase 6 |
| `FEED_STALENESS_SECONDS` | `30` | Seconds before a feed is declared stale | Phase 5/6 |
| `EOD_FLATTEN_TIME` | `15:55` | ET time to flatten all positions (U3) | §3/§7 |
| `HARD_STOP_TIME` | `11:00` | ET time after which no new entries are permitted | §7 |

---

## 7. Monitoring & Alerting

### Dashboard endpoints

| Endpoint | Description |
|---|---|
| `GET /health/ready` | 200 if all readiness checks pass; 503 otherwise |
| `GET /health/` | Full health snapshot: feeds, drift, latency, WS clients |
| `GET /api/state` | Current trading state, P&L, open positions |
| `GET /api/risk-events` | All risk events for the session |
| `WS /ws/live` | Push-based state updates, signal events, risk events |

### Alert severity thresholds

| Severity | When fired | Action |
|---|---|---|
| INFO | Normal trade entry/exit, session start/stop | Log only |
| WARN | Ghost position detected, qty mismatch, feed latency elevated, PDT advisory | Review at EOD |
| CRITICAL | Broker unreachable after max retries, U3 breach, kill-switch activated | Immediate manual response |

---

## 8. Client Sign-Off (U6 and Capital Ramp Gates)

Before enabling real capital, the following sign-offs must be recorded in PROGRESS.md:

```
CLIENT SIGN-OFF — [Date]
U6 Gate: [X] satisfied — [N] consecutive sim days @ [N]% accuracy
  (Sim period: [YYYY-MM-DD] to [YYYY-MM-DD])
Capital Tier: MICRO approved
  (Client: [name], date: [YYYY-MM-DD], method: [email/call/written])
Account type confirmed: [MARGIN/CASH]
Account equity at sign-off: $[N]
Broker/data vendor confirmed: Alpaca (alpaca-py 0.43.4) / Databento 0.80.0
Data subscription: Algo Trader Plus (SIP required; IEX-only insufficient)
Outstanding open questions: [list or NONE]
```

Do not set `LIVE_ENABLED=true` until this record is in PROGRESS.md.

---

## 9. Open Items Before Real Money

The following must be resolved before enabling live capital. Track in PROGRESS.md.

| # | Item | Blocker |
|---|---|---|
| 1 | **Data/broker vendor confirmed** | Alpaca paper sandbox tested; production keys + Algo Trader Plus subscription needed |
| 2 | **Account type + equity confirmed** | PDT rules depend on MARGIN vs CASH and equity level (§13.11) |
| 3 | **Halt feed** | `get_halt_status` (via `get_asset()`) does NOT detect intraday LULD halts. Requires Databento/Polygon halt feed for accurate halt detection. |
| 4 | **Level 2 depth** | L2 logic (Phase 8) requires Databento `mbp-10`. Not yet wired. |
| 5 | **Client sign-off** | Written sign-off per §8 above before `LIVE_ENABLED=true` |
| 6 | **Dry run on paper** | Minimum 1 full paper session with `LIVE_ENABLED=true` + production broker keys before real money |

---

*Last updated: 2026-06-26 (Phase 6 build)*
