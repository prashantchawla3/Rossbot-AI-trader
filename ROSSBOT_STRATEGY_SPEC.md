# ROSSBOT_STRATEGY_SPEC.md
**Authoritative Master Strategy Specification — Ross Cameron (DaytradeWarrior) Replication**
**Version: 2.0**
Source: ~1,750 YouTube videos (550 + 1,200) via 9 NotebookLM extractions + structured addendum.
Convention: Hard rules = consistent across all sources. ⚠️ CONFLICT = sources disagree; both values shown, code must make the threshold configurable.
V2 changelog: filled 8 V1 gaps (catalyst logic, L2 reading, candle rules, sizing math, halt entry, scanner numbers, time/trailing stops, multi-day continuation); added Section 13 (Automation Notes). New material flagged inline with `[V2]`.

---

## 1. Stock Universe Filters (Scanner Rules)

A symbol enters the watchlist ONLY if it passes the **Five Pillars**. All five are hard-gated.

```
PILLAR_1_PRICE:        price >= 2.00 AND price <= 20.00
PILLAR_2_FLOAT:        float <= 20_000_000          # hard ceiling
PILLAR_3_RVOL:         rvol_vs_50day_avg >= 5.0     # 500%
PILLAR_4_ROC:          change_pct_from_prev_close >= 10.0
PILLAR_5_CATALYST:     has_breaking_news == True    # "flame" flag
PASS_UNIVERSE = ALL of the above
```

`[V2]` **Two-tier scanner model.** The new research shows Ross runs a **wide morning net** then narrows to the **strict trade trigger**. These are distinct scans, not one threshold (resolves the apparent scanner-number conflict — see Section 9):
```
TIER_A_WIDE_NET (pre-market gap scan, casts wide):
   gap_or_change_pct >= 4.0   AND rvol >= 2.0  AND float <= 50_000_000  AND price in [1, 20]
TIER_B_FIVE_PILLARS (trade trigger, strict):
   change_pct >= 10.0 AND rvol >= 5.0 AND float <= 20_000_000 AND price in [2,20] AND catalyst
# A symbol surfaces on Tier A, but NO trade fires until it satisfies Tier B.
```

Ranking / attention filter (applied after Five Pillars):
```
IF market_rank_by_pct_gain(symbol) <= 3 THEN attention = "PRIME"
ELIF market_rank_by_pct_gain(symbol) <= 10 THEN attention = "WATCH"
ELSE attention = "IGNORE"
```

Preference scoring (not gates — used to rank candidates):
| Field | Hard Gate | Preferred | Optimal |
|---|---|---|---|
| Price | $2–$20 | sweet spot (see ⚠️) | — |
| Float | ≤ 20M | < 10M | < 5M, ideally < 1M |
| RVOL | ≥ 5x | — | 80x–100x+ |
| ROC | ≥ 10% | ≥ 25% | — |
| Total volume | liquid enough for size | millions of shares | 5M–25M shares by EOD `[V2]` |

`[V2]` Volume sweet spot refined: best results on names trading **5M–25M shares by end of day** (Source 2). Below = illiquid; far above = thickly traded / HFT-dominated.

⚠️ **CONFLICT — Price sweet spot:**
- Sources 1, 3, 5: **$5–$10**
- Source 2: range tops at **$10** (not $20)
- Source 4: sweet spot **$2–$10**; small-account challenges as low as **$1**
- `[V2]` New Source 1: avoids **< $2** (too congested, not enough cents/share). New Source 3: avoids **< $1** (ECN fees on large blocks destroy margin); scales down hard **> $20** (wide spreads/whipsaw).
- → `SWEET_SPOT_LOW`/`SWEET_SPOT_HIGH` config. Default $5–$10. Small-account mode allows $1 floor. Add `HARD_AVOID_BELOW = 2.00` (default ON for funded accounts).

⚠️ **CONFLICT — Float preference tier:**
- Sources 1, 4: ideal **< 5M**; Sources 1, 2: "under 10M" framing.
- `[V2]` Hard-ceiling conflict surfaced: most sources **≤ 20M**, but new Source 1 cites a looser **< 50M** ceiling for the *wide-net* gap scan only.
- → Keep ≤ 20M as the Tier-B trade gate. Use ≤ 50M only on Tier-A surveillance. Sub-tiers (<10M,<5M,<1M) = score weights.

`[V2]` **Catalyst detection — promoted from "highest-risk dependency" to a defined ruleset:**

Accepted catalyst types (any one satisfies Pillar 5):
```
biotech_clinical_or_FDA, topline_trial_results, earnings_beat,
major_contract_win (Nvidia/Tesla/Apple/Walmart-tier), AI_partnership,
crypto_treasury_or_bitcoin, space_theme, virus_outbreak_theme,
private_placement (see skip nuance), recent_reverse_split, recent_IPO, recent_SPAC,
>10pct_investor_stake (13D/13G)
```

ALWAYS-SKIP catalysts (hard blocks — these kill volatility or signal traps):
```
SKIP_1: buyout / being-acquired news        # price pins to deal price, trades sideways, zero vol
SKIP_2: ambiguous merger (who-buys-whom unclear)
SKIP_3: secondary offering / shelf dilution  # instantly kills momentum (PALI fixture)
SKIP_4: pump-and-dump (text/email newsletter promotions)  # insiders dump
SKIP_5: rehashed/recycled PR (same release reissued to inflate)
SKIP_6: five-cent-tick-pilot-program names   # mandated 5c spreads, scalp-unsafe
SKIP_7: heavy thickly-traded large-caps      # HFT makes action erratic
```
> Default: treat all buyout/merger language as SKIP unless the name is explicitly the dominant low-float gainer (acquirer, not target).

Catalyst CONFIRMATION logic (real vs noise):
```
REAL_CATALYST = (change_pct >= 10) AND (rvol >= 5) AND has_headline
# The market reaction IS the confirmation. Headline alone insufficient;
# extreme reaction with NO headline = the wildcard exception (Sec 12 EX1).
```

⚠️ **CONFLICT — Read-news-first vs buy-first `[V2]`:**
- Source 1: after scanner alert, step 2 = **read the news**, then act.
- Source 4: scanner spike → **confirm headline** → buy first pullback.
- Sources 2, 3: **"bite first, ask questions later"** — presses buy on the algo spike, reads headline *while managing the trade* (HFT moves in ms).
- → Reconcile via market state: HOT → `CATALYST_VERIFY_MODE = after` allowed; COLD → `before` mandatory. Default `before`.

News sources / feeds cited `[V2]`:
```
PRIMARY_HEADLINE: Benzinga feed; proprietary "News Desk"/"News Window" API (in-platform)
FILINGS_DILUTION:  BAMSEC / SEC EDGAR -> Form 3, Form 4, 13D, 13G, S-1, S-3, 10-Q
                   # check cash position + shelf registrations (dilution risk)
NEWS_TIMING:       cluster at top/bottom of hour (07:00, 08:00, 08:30 ET)
```

---

## 2. Entry Conditions (ALL must be true)

```
E1_UNIVERSE:     symbol passed Section 1 Five Pillars (Tier B)
E2_PULLBACK:     pullback occurred (1–3 red candles) after an upward surge
                 # NEVER chase a vertical green candle
E3_CROSSING:     current candle makes a new high vs previous candle ("candle over candle")
E4_MACD:         macd_line > signal_line AND histogram >= 0  (or crossing neg->pos)
                 # HARD BLOCK if MACD negative/red
E5_RETRACE:      pullback held the move (see ⚠️ depth conflict)
E6_L2_SUPPORT:   large resting buyers on bid (floor) OR large ask-seller just absorbed (Sec 2A)
E7_SPREAD_OK:    spread in [0.03, 0.10]   # [V2] NEW gate
ENTRY = E1 AND E2 AND E3 AND E4 AND E5 AND E6 AND E7
```

`[V2]` **E7 spread gate (NEW).** A **1-cent spread is NEGATIVE** (too thickly traded / HFT-dominated). He wants **3–5¢, even 5–10¢** = healthy volatility, room to scalp.
```
IF spread <= 0.01 THEN skip (too thick)
IF spread in [0.03, 0.10] THEN ideal
IF spread > 0.10 THEN caution (size down; slippage risk)
```

⚠️ **CONFLICT — Pullback retracement depth `[V2]`:**
- V1 / Source 3: must **hold ≥ 50%** (≤50% retrace); ideally stops at the **9 EMA**.
- Source 4: **not more than 25%** retrace.
- → `RETRACE_MAX` default **0.50** (invalidate beyond); `RETRACE_PREFERRED` **0.25** (full conviction).
```
E5_RETRACE: pullback_low >= surge_high - RETRACE_MAX * (surge_high - surge_start)
IF pullback_retrace <= 0.25 THEN conviction_bonus
IF pullback touches 9_EMA THEN conviction_bonus   # [V2] 9 EMA now tracked
```

Supporting / confirming signals (boost conviction → sizing, not gating):
```
VWAP_RECLAIM, PSYCH_LEVEL ($0.50/$1.00 break), GAP_AND_GO, OBVIOUS_FACTOR,
NINE_EMA_TOUCH [V2], GREEN_TAPE [V2] (burst of buy prints on ask, Sec 2A)
```

Entry discipline (behavioral gates):
```
IF setup not "obvious" THEN no_entry            # no stabs / no YOLO
IF pullback_count >= 3 THEN avoid               # 1st & 2nd only
IF anticipating_whole_dollar_break AND hidden_seller_present THEN no_entry  # [V2] GMBL
```

⚠️ **CONFLICT — Gap-and-Go entry timing (mid-candle vs candle-close) `[V2]`:**
- Sources 2, 3: **MID-CANDLE**, does not wait for close (HFT reacts instantly).
- Source 4: does **NOT** enter mid-candle; **"first candle to make a new high"** — waits for pullback candle close, buys the penny the next breaches its high.
- → `ENTRY_TRIGGER = {candle_close | mid_candle}`. Default `candle_close`. `mid_candle` only in HOT on gap-and-go.

⚠️ **CONFLICT — Short-borrow filter (original Source 3 only):** prefer HTB; avoid ETB. Optional weight, default OFF.

---

## 2A. Level 2 / Order-Book Reading Rules `[V2 — NEW, fills V1 gap]`

**Tape (Time & Sales):**
```
ENTRY_TAPE:  rapid burst of GREEN prints = buyers executing at ask (momentum real)
EXIT_TAPE:   burst of RED prints | tape speed stalls | large seller suddenly on ask
```

**Real floor vs spoof:**
```
REAL_FLOOR:  multiple MMs stacked at SAME price on bid (e.g. 4 MMs @ $2.25, 3–4 rows),
             esp. at $0.50/$1.00 -> sits, absorbs selling, prints execute
SPOOF:       large bid (e.g. 40k) VANISHES as price approaches
             OR ask disappears with NO matching green prints (pulled/fake)
             -> exit/avoid signal, NOT support/resistance
```

**Hidden seller / iceberg:**
```
ICEBERG:  massive green volume on tape BUT price won't advance AND displayed ask << absorbed
          (e.g. 10k bought, ask shows 100–600) -> do NOT buy in; if long, exit
ABSORBED (bullish trigger): price taps a level repeatedly, dips, later tap pushes THROUGH;
          OR visible block ticks down ("20k,19k,18k...boom") then breaks -> shorts squeeze, pop
          THIS is the buy trigger (E6).
```

---

## 3. Exit Rules (Priority order)

First matching rule fires.

```
P1 — HARD STOP (MENTAL): IF price <= stop_basis (pullback low) THEN sell_full() via hotkey
P2 — BREAKOUT-OR-BAILOUT (TIME STOP):
     IF price NOT advanced >= 0.10 within 60s AND not pulling_away THEN sell_full()  # [V2] +10c/60s
P3 — L2/TAPE REVERSAL: large ask-seller (~100k) | spoof | iceberg | red_tape_burst -> sell_full()
P4 — TOPPING TAIL: topping_tail|shooting_star|gravestone_doji|tweezer_top on high vol -> sell_full()
     # confirmed when NEXT candle makes new low [V2]
P5 — SCALE INTO STRENGTH: retest/break HOD OR hit $0.50/$1.00 -> scale_out(); move_stop_to_BE()
P6 — FIRST RED CANDLE CLOSE: first 1-min candle closes red -> sell_remaining()
P7 — PROFIT STOP / VWAP GUARD: significantly green -> trail_stop = slightly_below(VWAP)
P8 — LOST POPULARITY: attention rotates / no longer obvious -> exit_and_rotate()
```

`[V2]` **CRITICAL NEW RULE — NO LIVE STOP ORDERS (U13).**
```
NEVER rest a stop order in the broker — MMs stop-hunt visible stops.
ALL stops MENTAL, fired via panic hotkey on visual tape/candle cue.
# Bot: monitor internally, fire marketable-limit on breach; no native STOP order type.
```

`[V2]` **Move-to-breakeven trigger:** `IF unrealized_gain >= MOVE_BE_TRIGGER THEN stop = entry`. S3 = +0.05–0.10; S4 = +0.10 → default **0.10**.

`[V2]` **Trailing:** mentally trail to **low of last 1-min pullback**; optional **-5% trail after +10%** (S3).

`[V2]` **Scale-out cadence:** halve into resistance — 9,000→4,500→2,250→1,125 at successive $0.50/$1.00 (S2). Sell on the **ask** when scaling into strength.

`[V2]` **Avg hold:** ~5–10 min (winners); some breaking-news scalps < 1 min. Sanity bound, not a hard timer.

Profit target model:
```
PRIMARY_TARGET     = retest_or_break_of_HOD
BASE_HIT_TARGET    = entry + 0.15..0.20
RR_DERIVED_TARGET  = entry + 2 * risk_per_share   # enforce 2:1
```

⚠️ **CONFLICT — Scale fraction at first target:** S1 50% / S2 75% / S4 quarters-halves → `FIRST_SCALE_FRACTION` default 0.50, 0.75 hot variant.
⚠️ **CONFLICT — Stop basis:** pullback low (S1,4,5) vs prev 1-min candle low (S1,3) → `STOP_BASIS` default pullback_low; prev-candle for micro.

`[V2]` **Re-entry rule (NEW):** stop-out does NOT blacklist. Re-enter on fresh micro-pullback / VWAP reclaim / red-to-green (MSGM; −70¢ on 2k → re-entered 4k).
```
IF stopped_out AND fresh_valid_setup THEN re_entry_allowed
GUARD: must still pass Sec 2 AND not be revenge-driven (3-strikes / spiraling).
```

---

## 4. Chart Patterns (Ranked by conviction)

```
R1 First/Micro Pullback (HIGHEST, "bread & butter")   R7 Halt Resumption (Dip & Rip)
R2 ABCD ("W")                                          R8 Inverted Head & Shoulders
R3 Bull Flag / Flat-Top Breakout                       R9 Cup & Handle
R4 Blue Sky Breakout                                   R10 Red-to-Green
R5 Gap and Go                                          R11 Reverse Split Squeeze
R6 VWAP Break / Snap
```
Pattern rank feeds conviction score → position size (Section 6).

### 4A. Exact candle rules per pattern `[V2 — fills V1 gap]`

**Micro Pullback**
```
chart: 10-second or 1-minute
shape: 3–4 green candles surge UP, then 1–2 (max 3) pull back (can be one candle, or a candle
       opening "a teeny bit lower"); pullback on LIGHT volume
entry: first candle to make a NEW HIGH vs the previous (pullback) candle
ctx:   prefer $0.50/$1.00 level; ideally pullback kisses 9 EMA
inval: retrace > RETRACE_MAX (E5)
```

**Bull Flag / Flat-Top**
```
pole:  strong move up on INCREASING volume
flag:  1–3 red candles on LIGHT volume; 4–6 candles = weak (interest lost)
tight: consolidate in top 15–25% of pole range
entry: first green candle to new high on INCREASING volume
       (flat-top: break of horizontal resistance tested multiple times)
ideal: touch 9 EMA; must not retrace > 50%
```

⚠️ **CONFLICT — ABCD point lettering `[V2]`** (labels differ; geometry consistent: surge → pullback that holds → breakout of prior swing high):
- S2: A=low of 1st pullback, B=high of pop, C=low of 2nd pullback (C ≥ A), D=break over B.
- S3: A=initial low, B=first high, C=pullback low (C ≥ A), D=break of B.
- S4: A=initial high, B=pullback low, C=lower high failing A, D=breakout above C and A.
- → Implement geometrically, label-agnostic:
```
ABCD_VALID:
   surge -> pullback_low_1 = P1 -> pop_high = H1 -> pullback_low_2 = P2
   REQUIRE P2 >= P1                 # higher-low; cannot break first low
   ENTRY when price breaks H1 (prior swing high)
   INVALID if P2 < P1 (stair-stepping down -> void)
```

**Gap and Go** — see Section 2 entry-timing conflict.

**Failed-pattern / reversal (universal):**
```
FAIL_IF any:
   doji|spinning_top|shooting_star|gravestone_doji after up-move AND next candle new low
   false_breakout: breaches prior high by 1–5c then flushes; bid fails to catch up
   candle_under_candle (red breaks low of previous)
   drop below 9_EMA or VWAP | MACD negative cross | retrace > 50%
   breakout on suspiciously LIGHT volume after earlier spike   # RKDA fixture
```

---

## 5. Risk Management Rules

```
RR_RATIO:        expected_reward >= 2.0 * expected_risk
CUSHION_RULE:    IF day_pnl <= 0 THEN max_size = ICEBREAKER_SIZE   # never size up while red
THREE_STRIKES:   3 consecutive losing trades -> halt for day
NEVER_AVERAGE_DOWN: red -> forbid adds
NO_OVERNIGHT:    flat before close
SIMULATOR_GATE:  >=10 consecutive sim days @ >=60% accuracy before live
NO_LIVE_STOPS:   [V2] never rest a stop order (stop-hunt protection)
```

`[V2]` **Cushion → size-up gate (Source 1):**
```
starter_cap = 5000
IF realized_day_pnl < 1000 (or < 0.20/share secured) THEN shares <= starter_cap
ELSE allow scale beyond starter
```

⚠️ **CONFLICT — Max daily loss:** S1 $5k–7.5k / S2 $5k–6k / S3 $10k–20k / S4 $5k–$20k / S5 **10% acct** / addendum $50k. `[V2]` broker **hard lockout** commonly **$2k or $5k**.
```
MAX_DAILY_LOSS = min(account_value * 0.10, avg_winning_day_pnl)   # configurable
BROKER_HARD_LOCKOUT = config (default $5,000)                     # [V2] physical cutoff
IF day_pnl <= -MAX_DAILY_LOSS THEN shutdown_platform()
```

⚠️ **CONFLICT — Give-back stop:** 20% / 25–30% / 50%.
```
IF day_pnl <= peak_day_pnl * (1 - 0.25) THEN warn_and_reduce_size   # config 0.20–0.30
IF day_pnl <= peak_day_pnl * (1 - 0.50) THEN shutdown_platform()
```

`[V2]` **Day-of-week weighting (Source 1):** Monday most conservative (×0.5, worst day); Wed/Thu best (allow full); Fri/holiday/summer slow → tighten quality bar.

---

## 6. Position Sizing Logic

⚠️ **MAJOR CONFLICT — Sizing methodology `[V2]`:**
- **Source 1: NO risk/stop formula** — tiered FLAT blocks; starter ≤ 5,000; won't exceed 5k until ≥ $1,000 (or 20¢/sh) secured; full 30k–50k.
- **Sources 2,3,4: risk-per-share formula**, ~$1,000 max risk/trade, shares = risk_budget / stop_distance.
- → `SIZING_MODE = {flat_block | risk_formula}`, default `risk_formula`.

**risk_formula (default):**
```
risk_per_share = entry_price - stop_price
shares = floor( PER_TRADE_RISK_DOLLARS / risk_per_share )   # PER_TRADE_RISK_DOLLARS ~= 1000
# S2 table: stop 0.30->3,000 | 0.15->6,000 | 0.10->9,000
require( entry + 2*risk_per_share reachable )               # 2:1 before sizing
```

**flat_block (alt):**
```
starter 1,000/2,000/3,000 (S3) or 5,000 cap (S1) | mid 6,000 | full 9,000 (S2)
hot 12,000–15,000 (S2) ... up to 30k–50k (S1/S3)
```

Cushion + conviction + liquidity (both modes):
```
IF day_pnl <= 0: shares = min(shares, ICEBREAKER_SIZE)        # 1/4–1/5 of max
ELSE:            shares = min(shares, MAX_SIZE * conviction_multiplier)
conviction_multiplier = f(pattern_rank, rvol, float_tier, attention, spread)  # 0.25..1.0
shares = min(shares, LIQUIDITY_CAP(symbol))                  # never be the whole book
```

`[V2]` **Price/float modifiers:**
```
float < 1M  -> ⚠️ size DOWN (50c slippage, S3) / OR enter aggressively (S4) — disagreement
price 2–5   -> larger size OK (10k+)
price 9–20  -> size down (e.g. 1,500 x3 = 4,500 starter, S4)
COLD market -> cap 1,500–3,000 (S2) / 6,000–10,000 (S3)
```

Icebreaker: `1/4 or 1/5 of MAX_SIZE`.

⚠️ **CONFLICT — Absolute max size `[V2]`:** V1/S1/S3 up to **100k+** vs S4 **100k impossible, 10–15k** realistic. → `MAX_SIZE` configurable, never hardcode 100k; gate by `LIQUIDITY_CAP`.
⚠️ **CONFLICT — Small-account cap:** cash/small → **one trade/day** (unsettled funds). `MAX_TRADES_PER_DAY = 1`.

---

## 7. Time-of-Day Rules

```
PRIMARY_WINDOW:   07:00 <= now <= 10:00 ET
AGGRESSIVE_OPEN:  09:30 <= now <= 10:00 ET
PREMARKET_EDGE:   prefer pre-market (fewer halts)
NEWS_CLUSTER:     07:00 / 08:00 / 08:30 ET  # [V2]

IF now > HARD_STOP_TIME THEN no_new_entries
IF time_since_last_trade > 60min THEN stop_for_day
IF now >= 10:00 AND zero_trades_taken THEN stop_for_day   # [V2] Source 3
AFTERNOON: no trades unless picture_perfect_setup
```

⚠️ **CONFLICT — Scan start:** 4/6/6:30/7 AM → default `SCAN_START = 07:00`; earlier surveillance flag.
⚠️ **CONFLICT — Hard stop:** 10:00/10:30/11:00 → default `HARD_STOP_TIME = 11:00`; tighten cold.
`[V2]` ⚠️ **CONFLICT — Pre-market desk routine:** S2 arrives **8:45–9:00**, scans 9:15, meditates pre-9:30 (open-focused) vs others wake 6:15–7:30 / desk 6:45 / fire 7:00 (pre-market-focused). Two operator profiles; default pre-market.

Afternoon exception:
```
IF major_event (high-profile IPO launch) THEN afternoon_trading_allowed
# Counter-fixture: GME -$8k at 2PM on a declared no-trade day = violation, NOT precedent.
```

---

## 8. Market Condition Adjustments (Hot / Cold / Rehab)

```
STATE = {HOT, COLD, REHAB}
```

`[V2]` **State-detection heuristics (NEW):**
```
HOT:  winners hold large extensions (500% moves), base hits -> home runs, selling "too soon",
      long green streaks, multiple names up 100%+ with float <5M; gappers break PM highs, surge into halts
COLD: winners shrink, red days more frequent AND larger, breakouts fail instantly ("jackknife"),
      leading gappers fade hard, volume choked, top gapper only up ~20–40% / float >30–100M / price extreme
```

**HOT:** size up (A+ up to 50k–100k *subject to liquidity & Sec 6 conflict*), may accept B/C, trade longer, goal $20k–$50k+; may set `CATALYST_VERIFY_MODE=after`, `ENTRY_TRIGGER=mid_candle`.
**COLD:** reduce 50–75% (cap ~10k or 1.5–3k), A+ only strict Five Pillars, shorten window, goal ~$5k, account guards (warnings/remove cash), EX1 & EX2 DISABLED.
**REHAB (after outlier loss):**
```
ENTER:  single_loss outlier OR severe drawdown
size:   micro — [V2] as low as 100 sh up to 1,000–10,000; REMOVE buy hotkey from keyboard
bar:    A+ only; aim 50–60% accuracy base hits
EXIT:   50% of drawdown recovered AND multi-day green cushion rebuilt
```

---

## 9. Scanner Definitions

`[V2]` Reconciled into the **two-tier model**. Numeric conflicts = different scanners, not contradictions.
```
TOP_GAINERS_SCAN:        sort by %change vs prev_close; price > $0.50
GAP_SCAN (Tier A wide):  gap >= 4–5% (some 2%), price $1–20, float <50M, rvol >=2x   # [V2]
LOW_FLOAT_TOP_GAINER:    top gainers WHERE float < 5M AND price < $20
FIVE_PILLAR_SCAN (Tier B):price 2–20 AND float <10M AND rvol>5x AND roc>10% AND breaking_news
HOD_MOMENTUM_SCAN:       AUDIO alert on new intraday high; weight at top/bottom of hour
RUNNING_UP_SCAN:         surging hard but BELOW HOD ("5% in 5min" / "10% in 10min")
HALT_SCAN:               entering/exiting LULD halts
REVERSE_SPLIT_IPO_SCAN:  recent reverse splits + IPOs
LOW_FLOAT_FORMER_MOMO:   [V2] faster-alerting scan for immediate breakouts of past runners
CONTINUATION_SCAN:       [V2] massive movers in prior ~2 weeks (~30% of profits)
ALERT_TAGS: 52_week_breakout, low_float_former_runner, squeeze_alert
```

⚠️ **CONFLICT — Scanner numbers (resolved by tier):** %chg 4% (A) vs 10%+ (B); RVOL 2x (A) vs 5x (B); float <50M (A) vs <20M/<10M (B); price $1–10 (S2) vs $2–20 (most). → Tier A net, Tier B gate; trades require Tier B.
⚠️ **CONFLICT — Platform `[V2]`:** "Day Trade Dash"/"Ross's Scanners" (S1,3,4) vs "Trade Ideas" (S2). → Vendor-agnostic native reimplementation. Audio-alert sounds are UI artifacts.

---

## 10. Order Execution Rules (Hotkeys, order types)

**HARD RULE: LIMIT ORDERS ONLY. Never market orders.**
```
BUY:  limit @ ask + OFFSET  (OFFSET in {0.05, 0.10})
SELL: limit @ bid  (or ask when scaling into strength to maximize fill)  # [V2]
```

Hotkey map:
```
Shift+1..Shift+10  -> BUY block N (1,000..10,000), limit @ ask+offset
Ctrl+Z             -> SELL FULL, limit @ bid (panic)
Ctrl+X (or Ctrl+K) -> SELL 50%   # [V2] Ctrl+K alias (Source 2)
Ctrl+C             -> SELL 25%
```

> AUTOMATION NOTE: hotkeys = human construct. Replicate as parameterized limit orders w/ offset;
> "Shift+N" → size tiers; "Ctrl+*" → scale fractions; "Ctrl+Z panic" = cancel-all + flatten.
> **No native STOP order type** (U13). Broker API must support marketable-limit-with-offset + partial sells.

---

## 11. Unbreakable Rules

```
U1  No Five-Pillar symbol -> NO_TRADE_DAY.
U2  Never average down.
U3  Never hold overnight.
U4  Strict daily stop. max_daily_loss OR 50% give-back -> shutdown.
U5  3 consecutive losses -> stop for day.
U6  Simulator-first: >=10 sim days @ >=60% before live.
U7  Limit orders only.
U8  No counter-trend (no bottom-fishing crashes; never short new-high momentum).
U9  No illiquid trades (e.g. +900% on 266k sh).
U10 Technicals over bias.
U11 Walk away when emotionally hijacked / after 3 strikes.
U12 No YOLO.
U13 [V2] No resting stop orders (stop-hunt protection) — mental stops via hotkey only.
U14 [V2] Never anticipate a whole/half-dollar break when a hidden seller is present (GMBL).
U15 [V2] Never trade buyout/secondary/recycled-PR catalysts (price pins / dilution).
```
⚠️ Simulator accuracy/duration: only original Source 1 gives "10 days / 60%" — canonical.

---

## 12. Edge Cases and Exceptions

```
EX1 — Chinese/Foreign Wildcards: low-float Chinese/HK IPO or reverse-split AND undeniable #1 gainer
      -> catalyst MAY be waived. High-risk "hot potato" (dumps 50%+). DISABLED if COLD.
EX2 — "Bite First, Ask Questions Later": HOT AND parabolic -> may enter before verifying news.
      DISABLED if COLD. (Ties to CATALYST_VERIFY_MODE.)
EX3 — Short-sell danger: never short front-side low-float momentum (INHD +5,000%).
EX4 — Spoofing on L2: fake orders -> exit/avoid, not support/resistance.
EX5 — [V2] Halt-DOWN avoidance: flush below VWAP, halt down, resume lower -> DO NOT touch
      unless reclaims AND holds above VWAP.
EX6 — [V2] Algo bid-pull trap: HFT yanks MM bids instantly, winner -> flush (CADL).
      Never rely on one large bid as guaranteed support; confirm with prints.
```

### 12A. Halt Resumption — exact entry rules `[V2 — fills V1 gap]`
```
PRE-HALT (aggressive, S2): squeezing toward LULD band on L2 -> add shares just before halt, expect gap-up.
POST-HALT (S3,S4): after 5-min pause, watch split-second micro-dip (shakes weak hands), buy the rip in seconds.
   Trigger = "pause + green through L2" OR massive buyer appears on bid; limit to catch dip (buy $7.01 after $7.08 halt).
CONFIRM: read imbalance/resumption quote (free brokers hide it); resume FLAT/HIGHER = bullish;
         resume LOWER = weakness -> skip / stop out.
HALT-DOWN: avoid (EX5).
```
⚠️ **CONFLICT — pre vs post halt:** S2 buys *into* the halt; S3–4 buy the *resumption*. `HALT_MODE = {pre_halt | post_halt}`, default `post_halt` (pre-halt = gap-through-pause risk).
Fixtures: ARM ($55.84→$56.79), CTRM ($6.41→$16.50–18.50), HKD ($180 +$17/sh), PHVS ($5.41→$7.00), KALA (4 halt-ups), SNGX ($6.35→$6.60).

### 12B. Multi-Day Continuation — rules `[V2 — fills V1 gap]`
```
ELIGIBLE_DAY2: Day-1 move >=100% AND held gains into close.
DONE_IF: today_rvol < 25% of prev_day_volume | retrace > 50% of Day-1 move
         | MACD negative cross | breaks-and-holds below VWAP
FRESH_NEWS: NOT required (Day-1 squeeze is ongoing catalyst); fresh news re-ignites.
ADJUSTMENTS (more conservative):
   shift 1-min -> 5-min (1-min too choppy/crowded Day 2); smaller size;
   avoid gap-and-go and aggressive HOD breakouts;
   trade "first DAILY candle to make a new high" = break of prev-day high;
   trade breaks of descending resistance from Day-1 highs; base hits after it holds VWAP.
NOTE: ~30% of profits from continuation (S3); Day-1 front-side still preferred (S4).
```

### Labeled trade examples (regression fixtures)
| Symbol | Outcome | Lesson |
|---|---|---|
| SLXN | +$49k | 1st 1-min micro-pullback off $18 → $30 |
| MLGO | +$50k | +432% on 300M vol; all 5 pillars |
| SPRC | win | 7:00 gap → pullback → inv H&S + ABCD → VWAP break |
| ARM | win | IPO halt resumption, cents scalp |
| CTRM/HKD/PHVS/KALA/SNGX | win | halt dip-and-rip fixtures (12A) |
| GLTO | major loss | sized up while RED + averaged down (U2/CUSHION) |
| ESTR | ~$30k loss | FOMO top-buy 9k, high float, no news, pre-halt (no pullback) |
| 18-sec flush | $6,362 loss | cut immediately, no average-down (correct) |
| Snowball day | big loss | failed to walk away after 20% give-back → spiraled |
| GMBL | loss | anticipated $7 break with hidden seller; got stubborn (U14) |
| PALI | loss | secondary offering killed momentum (U15) |
| PTPI | small loss | buyout news (later fraud) — never trade buyouts |
| RBLX | $500 loss | high-float low-% gapper, boredom trade |
| RKDA | $4,200 loss | added at top into topping tails; breakout on light volume |
| MYT | $1,500 loss | weak Friday gap scanner; chased thin setup |
| NIXX | $70 loss | iceberg seller — correct fast bailout |
| TIX | $1,200 loss | fake-out chop |
| GME | $8,000 loss | traded 2PM on a no-trade day; past 11AM; FOMO (U11/Sec7) |
| TRNR | biggest monthly loss | oversized on undeserving setup |
| INHD | (danger) | +5,000% — never short front-side momentum (EX3) |

---

## 13. Automation Implementation Notes `[V2 — NEW]`

For each hard-to-automate rule: why hard / best proxy / data source / risk if proxy wrong.

**13.1 Catalyst detection (Pillar 5)**
- *Hard:* "breaking news" + real-vs-pump/rehash/buyout/dilution is semantic; "flame" flag proprietary.
- *Proxy:* NLP classifier over real-time news; tag type (FDA, M&A, offering, contract, theme). Gate with reaction proof (≥10% AND ≥5x RVOL). Hard-block SKIP categories via keyword + filing check.
- *Data:* Benzinga Pro API (or equiv) + SEC EDGAR/BAMSEC for S-1/S-3/424B (dilution), 13D/13G/Form 4; halt feed.
- *Risk:* Trading a secondary/buyout = momentum death (PALI/PTPI). Bias classifier toward *skip* on ambiguity; false-negative is safe (no trade).

**13.2 Level 2 / tape (E6, E7, 2A, Exit P3)**
- *Hard:* needs true depth + T&S; spoof/iceberg heuristic; many retail APIs top-of-book only.
- *Proxy:* full-depth + tape (Nasdaq TotalView). Iceberg = executed >> displayed-ask w/ no advance. Spoof = cancel with no matching prints as price nears. Green-tape = ask-side execution rate.
- *Data:* TotalView/ArcaBook + tick T&S; broker exposing halt imbalance/resumption quotes.
- *Risk:* Spoof-as-floor → premature entry into a flush (CADL); iceberg-as-breakout → buying absorption (GMBL/NIXX). Require prints-confirmation before E6.

**13.3 "Obvious"/attention (OBVIOUS_FACTOR, Exit P8)**
- *Hard:* qualitative.
- *Proxy:* %-gain rank ≤3 + RVOL percentile + news/social mention velocity.
- *Data:* full-market scanner snapshot + optional social-volume feed.
- *Risk:* late rotation / holding a faded name. Keep as score weight, not hard gate.

**13.4 Mental stops / no-live-stops (Sec 3, U13)**
- *Hard:* forbids resting broker stops, but bot needs deterministic exit.
- *Proxy:* internal price monitor fires marketable-limit on breach; never route native STOP. Low-latency loop.
- *Data:* real-time top-of-book; sub-second loop.
- *Risk:* latency → worse fill than a resting stop. Mitigate with a *hidden* catastrophic broker stop far below the mental level as backstop only.

**13.5 Time stop (+10¢/60s) & breakout-or-bailout**
- *Hard:* "pulling away"/"hesitates" is judgment.
- *Proxy:* quantified — unrealized < +0.10 at T+60s and no higher-highs on rising volume → flatten.
- *Data:* fills + tick prices + volume.
- *Risk:* premature exit on slow-but-valid mover. Tune `BAILOUT_SECONDS`/`BAILOUT_MOVE` per regime; backtest.

**13.6 Sizing methodology conflict (Sec 6)**
- *Hard:* flat-block vs risk-formula; unbounded vs liquidity-bound max.
- *Proxy:* default risk_formula ($1k/stop), clamp by `LIQUIDITY_CAP = f(ADV, depth)`.
- *Data:* ADV + real-time depth.
- *Risk:* oversize → become the book → self-slippage (TRNR/ESTR). Cap order at % of top-N-level depth.

**13.7 Halt resumption (12A)**
- *Hard:* needs resumption/imbalance quotes retail hides; pre-halt = gap risk.
- *Proxy:* default post_halt; consume LULD + reopen auction; enter only if resume ≥ prior price w/ green prints.
- *Data:* LULD/halt feed w/ auction data; broker that trades the reopen.
- *Risk:* buying a halt-down resumption (EX5) = immediate loss. Hard-block unless VWAP reclaimed.

**13.8 Pattern recognition (4A)**
- *Hard:* geometry codeable, but "first new high" timing + mid-vs-close conflict; ABCD labels differ.
- *Proxy:* label-agnostic geometry (4A ABCD block); default `ENTRY_TRIGGER=candle_close`; 9 EMA/VWAP/MACD on 1-min + 10-sec.
- *Data:* 10-sec + 1-min OHLCV.
- *Risk:* mid-candle chases noise in cold tape; candle-close misses fastest HOT moves. Gate mid-candle to HOT.

**13.9 Market-state classifier (Sec 8)**
- *Hard:* HOT/COLD is gestalt.
- *Proxy:* rolling features — gapper follow-through rate, breakout success %, avg green/red day size, count of >100%/<5M-float names. Threshold into HOT/COLD/REHAB.
- *Data:* historical + intraday scanner stats; own trade ledger.
- *Risk:* HOT misread enables EX1/EX2/mid-candle/oversize in cold tape → jackknife losses. Bias COLD on uncertainty.

**13.10 Multi-day continuation (12B)**
- *Hard:* "held gains reasonably" + frame shift are judgment.
- *Proxy:* eligibility = Day-1 ≥100% AND close ≥ X% of Day-1 high; done-conditions numeric (RVOL<25% prior, retrace>50%, MACD cross, VWAP loss). Auto-switch 5-min + reduced size.
- *Data:* daily + intraday bars, prior-day volume.
- *Risk:* Day-2 dumps with no fresh news; keep size reduced, require VWAP-hold confirmation.

**13.11 Regulatory / account**
- PDT (<$25k → ≤3 day-trades/5 days): enforce `MAX_TRADES_PER_DAY`/PDT guard before small-account mode.
- Cash account: T+1/unsettled → one-trade-per-day.
- Wash-sale tracking (high-frequency re-entries trigger it).
- Locate/HTB rules if short logic added later (out of scope).
- SSR + LULD bands affect halt logic.
- *Risk:* PDT violation freezes account; confirm account type/equity at startup, hard-gate.

---

## Appendix A — Open Conflicts Requiring Client Decision
| # | Parameter | Values | Default proposed |
|---|---|---|---|
| C1 | Price sweet spot | $5–10 / $3–8 / $2–10 / ≤$10 | $5–$10 (config) |
| C2 | Max daily loss | $5k–7.5k / $10k–20k / 10% acct / $50k / lockout $2–5k | min(10% acct, avg win day) |
| C3 | Give-back stop | 20% / 25–30% / 50% | warn 25%, hard 50% |
| C4 | First scale fraction | 50% / 75% | 50% |
| C5 | Stop basis | pullback low / prev-candle low | pullback low |
| C6 | Scan start | 4 / 6 / 6:30 / 7 AM | 07:00 ET |
| C7 | Hard stop time | 10:00 / 10:30 / 11:00 | 11:00 ET (tighten cold) |
| C8 | HTB-only filter | Source 3 only | OFF (optional) |
| C9 | Pullback retrace depth `[V2]` | ≤25% (S4) / ≤50% (S3) | max 50%, preferred 25% |
| C10 | Sizing methodology `[V2]` | flat-block (S1) / risk-formula (S2,3,4) | risk_formula |
| C11 | Absolute max size `[V2]` | 100k+ (S1,S3) / 10–15k (S4) | config, liquidity-capped |
| C12 | Gap-and-go entry timing `[V2]` | mid-candle (S2,3) / first-candle-close (S4) | candle_close (mid in HOT) |
| C13 | Catalyst verify `[V2]` | before (S1,S4) / after (S2,S3) | before (after in HOT) |
| C14 | Halt entry `[V2]` | pre-halt (S2) / post-halt (S3,S4) | post_halt |
| C15 | Move-to-BE trigger `[V2]` | +5–10¢ (S3) / +10¢ (S4) | +0.10 |
| C16 | Platform `[V2]` | Day Trade Dash / Trade Ideas | vendor-agnostic reimpl |

## Appendix B — Automation Risk Flags (architect notes)
- **Catalyst detection** (Pillar 5): defined skip-list + reaction-proof gate (13.1); bias to skip on ambiguity.
- **Level 2 / tape** (E6/E7/2A): needs true depth + tick tape + halt imbalance quotes; most retail APIs insufficient (13.2).
- **No-live-stops** (U13): emulate mental stops via internal monitor + marketable-limit; never route native stops (13.4).
- **"Obvious"/attention**: proxy via %-gain rank + RVOL percentile + mention velocity (13.3).
- **Sizing/liquidity**: clamp every order by `LIQUIDITY_CAP`; oversize is the recurrent blow-up cause (ESTR/TRNR/GLTO) (13.6).
- **Market-state classifier**: gates EX1/EX2/mid-candle/oversize; bias COLD on uncertainty (13.9).
- **Regulatory:** PDT, cash-settlement, wash-sale, SSR/LULD; confirm account type at startup (13.11).
