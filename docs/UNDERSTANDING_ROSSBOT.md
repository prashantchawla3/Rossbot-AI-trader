# Understanding RossBot — A Plain-English Guide

> **Who this is for:** anyone — including someone who has *never* touched trading — who
> opens this project and thinks "what is this and how does it work?" This guide assumes
> zero trading knowledge and zero coding knowledge. It explains the whole system from the
> ground up, then gives a structured technical reference at the end.
>
> **One-sentence summary:** RossBot is a software robot that day-trades small US stocks the
> way trader Ross Cameron does — automatically, faster, and with strict, unbreakable safety
> rules. Right now it runs in **paper (practice) mode** with fake money on a real market feed.

---

## Table of Contents

1. [Part 1 — The absolute basics](#part-1--the-absolute-basics)
2. [Part 2 — How the bot makes a trade (the pipeline)](#part-2--how-the-bot-makes-a-trade-the-pipeline)
3. [Part 3 — Where the AI actually fits in](#part-3--where-the-ai-actually-fits-in)
4. [Part 4 — Your dashboard, page by page](#part-4--your-dashboard-page-by-page)
5. [Part 5 — Your big questions, answered directly](#part-5--your-big-questions-answered-directly)
6. [Part 6 — Where the project actually stands](#part-6--where-the-project-actually-stands)
7. [Part 7 — A glossary of every term](#part-7--a-glossary-of-every-term)
8. [Appendix A — A concrete trade, step by step](#appendix-a--a-concrete-trade-step-by-step)
9. [Appendix B — Technical reference (engine internals)](#appendix-b--technical-reference-engine-internals)
10. [Appendix C — Technical reference (backend API)](#appendix-c--technical-reference-backend-api)

---

# Part 1 — The absolute basics

## What is a stock, and what is "trading"?

A **stock** (also "share" or "equity") is a tiny piece of ownership in a company. Companies
have millions of these pieces, and people buy and sell them all day on the **stock market**.

A **symbol** (or "ticker") is the short code for a company's stock. Apple is `AAPL`, Tesla is
`TSLA`. When the app shows "MLGO" or "DEMO", those are symbols — shorthand names for specific
companies' stocks.

**Trading** = buying a stock at one price and selling at another, hoping to sell higher than
you bought. Buy 100 shares at $10, sell at $11 → you made $100 (minus fees).

**Day trading** specifically means: buy and sell on the *same day*, often holding for only a
few minutes. You never keep the stock overnight. You're not investing in the company's future
— you're catching short, fast price moves.

## Who is Ross Cameron, and what's his "strategy"?

**Ross Cameron** (brand: "Warrior Trading" / "DaytradeWarrior") is a famous American day trader.
He's known for a very *specific, repeatable* style: he hunts for small, cheap stocks that are
suddenly spiking on breaking news, jumps in for a few minutes to ride the momentum, then gets
out fast — all under strict rules about how much he's willing to lose.

A **"strategy"** is just a fixed set of rules: *what* to buy, *when* to buy it, *how much* to
buy, and *when* to sell. Ross has taught his rules across ~1,750 YouTube videos. This project
turns those rules into a **bot** — software that follows them automatically, with more
discipline than a human (no fear, no greed, no "let me hold a bit longer").

**That is the entire project:** a robot that trades small US stocks the way Ross Cameron does,
with the risk controls he preaches, executed by a computer.

## So what was actually built?

Three things that work together:

1. **A "brain"** (the Python backend) — watches the market, finds Ross-style opportunities,
   decides whether to trade, and places orders. *This is the bot itself.*
2. **A "control panel"** (the dashboard / website) — the screens where a human watches what the
   brain is doing, sees its decisions, and presses emergency buttons.
3. **A connection to a broker** (a company called **Alpaca**) — the actual pipe to the stock
   market that places real orders.

> **Key mental model:** The website is *just the dashboard* — a window into the brain. The real
> trading happens in the brain (backend) and gets sent to the broker. The website only *shows*
> you what's happening; it doesn't do the trading itself.

---

# Part 2 — How the bot makes a trade (the pipeline)

Here's the assembly line, start to finish. Everything in the app maps to one of these five stages.

```
1. SCANNER      →  2. STRATEGY     →  3. RISK MANAGER  →  4. EXECUTION  →  5. JOURNAL
   "what's hot?"    "is this a        "are we ALLOWED     "place the       "write down
                     Ross setup?"      to trade? how much?"  order"          what happened"
```

## Stage 1 — The Scanner ("what's worth watching?")

The US market has thousands of stocks. The **scanner** is the bot's spotlight — it constantly
filters that huge list down to a tiny handful worth attention. Think of a bouncer scanning a
crowd for the few people who match a very specific description.

It works in two stages:

- **Tier A — the wide net.** "Show me any small stock moving a lot right now." ~100–200
  candidates. *Interesting*, but not yet *tradeable*.
- **Tier B — the strict gate.** From Tier A, only stocks that pass **all five** of Ross's hard
  requirements make it through. These are the only ones the bot will ever trade.

### The "Five Pillars" (the five hard requirements)

A stock must pass **all five** to be tradeable. This is the heart of Ross's stock-picking.

| Pillar | Requirement | Plain English |
|---|---|---|
| **P1 — Price** | $2–$20 | Not too cheap (junk), not too expensive (sluggish). The sweet spot where small stocks move fast. |
| **P2 — Float** | ≤ 20 million shares | **"Float"** = how many shares are actually available to trade. *Fewer* shares = the price moves more violently when buyers pile in (a small boat vs. a cargo ship). Ross wants small boats. |
| **P3 — RVOL** | ≥ 5× | **"RVOL" (Relative Volume)** = how busy the stock is *today* vs. a normal day. 5× = 5 times more trading than usual — a sign something big is happening *right now*. |
| **P4 — Up ≥ 10%** | already up 10%+ today | The stock must already be making a real move. The bot doesn't predict; it follows momentum that's already started. |
| **P5 — Catalyst** | real breaking news | There must be a *reason* — an FDA approval, an earnings beat, a big contract. No news = no trade. This is where the **AI** comes in (see Part 3). |

So "RVOL", "float", "catalyst", "symbol" are just the things the bot checks on every stock.
When the dashboard shows a watchlist with columns like Price, Chg %, RVOL, Float, Pillars 5/5 —
*that is the scanner's output*. "Pillars 5/5" means the stock passed all five and is tradeable
(Tier B). "3/5" means it failed two and is just being watched (Tier A).

## Stage 2 — The Strategy Engine ("is this the right moment to buy?")

Passing the Five Pillars means a stock is *worth trading*. But Ross doesn't buy the instant a
stock qualifies — he waits for a precise *moment*.

The key Ross idea: **don't chase a rocket straight up; wait for it to take a small breath, then
buy as it resumes.** A stock spikes up, pauses/dips slightly (a "pullback"), and the bot buys
right as it starts climbing again. Buying into the pause is safer and gives a clear "get out"
point if it's wrong.

To pull the trigger, the bot checks **seven entry gates (E1–E7)** — and *all* must be true
(these are the E1–E7 you see in the Signals feed):

- **E1** — Passed the Five Pillars (already done).
- **E2** — There was a pullback (a small dip after the surge) ✅ the "breath."
- **E3** — Price is now breaking back up to a new high ✅ the "resume."
- **E4** — **MACD** is positive. (MACD is a standard momentum gauge; "positive" = momentum is
  up, not fading. If it's negative, the bot refuses — hard stop.)
- **E5** — The dip wasn't *too* deep (a shallow dip is healthy; a deep one means the move is dying).
- **E6** — There are real buyers underneath supporting the price. *(Turned off in the current
  demo — see Part 5.)*
- **E7** — The "spread" is healthy. (**Spread** = the gap between the highest price buyers offer
  and the lowest price sellers ask. A few cents is ideal; too tight or too wide is bad.)

If even one gate fails → **no trade.** This is why real auto-trades are *rare* — the stars
rarely all align. That's by design; Ross passes on most stocks too.

When all 7 pass, the bot also recognizes *which* chart pattern it is (Ross has names like
"Micro Pullback," "Bull Flag," "ABCD") and scores its **"conviction"** — a confidence number
based on pattern quality, how high the RVOL is, how small the float is, etc. Higher conviction
→ the bot is allowed to buy more shares.

## Stage 3 — The Risk Manager ("are we ALLOWED, and how much?") ← most important

This is the bot's **safety brain**, and it's the single most important piece. Every proposed
trade must pass through it, and **it can VETO (block) any trade no matter how good it looks.**
The client's money is real, so the rule is "brakes before engine."

**Job 1 — Veto checks (block the trade entirely if any is true):**

- Already lost too much today (**daily loss limit**) → stop trading for the day.
- Lost **3 trades in a row** ("3-strikes rule") → stop for the day. (Losing streaks snowball;
  this prevents revenge-trading.)
- The trade doesn't offer at least **2:1 reward-to-risk** (must stand to gain at least twice
  what you'd lose).
- It's past the cutoff time of day (Ross trades mornings).
- News is on a forbidden list (buyouts, stock dilution — "news" that *looks* exciting but traps you).
- …and several more.

**Job 2 — Position sizing (decide how many shares):**

It calculates how many shares to buy so that *if the trade goes wrong, you only lose a pre-set
small amount.* It then shrinks that further if you're already down for the day (the
**"cushion / icebreaker"** rule — trade smaller when losing), if conviction is low, or if the
market is choppy.

> When the dashboard shows "**Veto**" or "SIGNAL BLOCKED" or a **Risk Events** log entry —
> that's this stage saying "no." A quiet risk-events page is a *good* sign.

## Stage 4 — Execution ("place the order")

Once risk approves, this stage sends the order to the broker (Alpaca). Two Ross rules matter:

- **Limit orders only, never "market" orders.** A "market order" says "buy at *whatever* price"
  — dangerous on fast stocks. A "limit order" says "buy, but only up to *this* price." Safer.
- **"Mental stops," not real stop orders.** A "stop" is your pre-decided exit-if-it-goes-wrong
  price. Most people place that as a *visible* order at the exchange — but professional sellers
  can *see* those and hunt them. So the bot keeps the stop *in its own memory* and only fires a
  sell the instant the price is hit. Same protection, invisible to the market. (That's the
  "Mental Stop" term in the glossary.)

It also manages the exit — selling part of the position into strength, moving the stop up to
lock in profit, and dumping the whole thing if the move dies.

## Stage 5 — The Journal ("write down what happened")

Every decision, order, and veto is logged. This is the **Journal** page — the end-of-day record
of trades, wins, losses, and why. It's also how the bot proves it's good enough to eventually
use real money (see Part 6).

---

# Part 3 — Where the AI actually fits in

Most of this bot is *fixed rules*, not AI — intentionally. Ross's strategy is rules, and rules
are predictable and auditable. But there are **two specific places** where genuine AI (a large
language model, like Claude) is used:

1. **Catalyst detection (Pillar 5) — the main one.** Deciding "is this news a real catalyst or
   a trap?" is a *language* problem — you have to *read and understand* a headline. That's
   exactly what AI is good at and rules are bad at. The bot feeds breaking-news headlines to an
   AI model (Claude Haiku by default), which classifies them: "FDA approval → tradeable" vs.
   "stock offering → skip." When in doubt, it says "unverified" and the bot *doesn't* trade
   (safe by default).

2. **The AI Analysis page — your on-demand grader.** You type any symbol, and the AI grades it
   against all of Ross's rules and tells you in plain English "Ross would trade this ✅" or
   "Ross would skip this ❌," with reasons. This is a *helper for the human* — not part of the
   automatic loop.

> **In short:** the AI reads the news and grades setups; the fixed rules do everything else.
> The "model picker" (Claude / GPT / NVIDIA / Gemini) just lets you choose *which* AI company's
> brain does that grading.

---

# Part 4 — Your dashboard, page by page

Each page is a window into a stage above. The top menu has five tabs (plus two more pages
reachable directly).

### 🟦 Command (Command Center) — your cockpit and manual-trading desk

The "everything" page. Shows:
- **Alpaca Account panel** — broker connection: CONNECTED?, balance ("equity"), buying power.
  A "PAPER" badge means fake money.
- **Metric cards** — Day P&L (profit/loss today), Win Rate, Losing Streak, Open Positions.
- **Bot Controls** — the big safety buttons: **Flatten All** (sell everything now), **Pause**,
  **Halt Day**, plus config toggles (auto-trading on/off, daily loss limit, scan interval).
- **Place a Test Trade** — *you* can manually buy/sell by hand. It still goes through the Risk
  Manager, so the bot can veto or resize even your manual order.
- **Live Scanner Signals** — the current Tier A / Tier B watchlist, with a "Scan now" button.

### 🔍 Watchlist — the scanner's output + a live price chart

A table of stocks the bot is watching (Tier A = wider pool, Tier B = passed all 5 pillars), and
a **TradingView chart** (the candlestick price graph) for whichever symbol you click. The
"E1✓ E2✗ …" line shows exactly which entry gates a stock is passing or failing right now.

### ⚡ Signals — open positions + the live decision feed

The top shows stocks the bot currently holds, with buttons to close them, scale out, or move
the stop. The bottom is a running feed of *every* decision: 🟢 a trade opened, 🔴 a trade
blocked (and why), ⚪ an informational note. This is the bot "thinking out loud."

### 🧠 AI Analysis — ask the AI to grade any stock

Type a symbol, pick an AI model, get a "trade it / skip it" verdict with the Five Pillars and
seven gates checked off, plus a suggested trade you can execute (through the risk gate) or ignore.

### 📖 Journal — today's completed trades and the session scorecard

Win rate, profit factor, best/worst trade, plus a plain-English **Rules Reference** (a built-in
FAQ). Two more pages are reachable directly: **Health** (is data flowing fast enough?) and
**Risk & Safety** (the log of every time a safety rule fired).

> Every confusing term in the UI has a hover-tooltip — the developers built a whole plain-English
> glossary (`dashboard/lib/glossary.ts`) so an operator never needs the technical spec.

---

# Part 5 — Your big questions, answered directly

### "Can the bot even trade? Where and how?"
**Yes — it can place real orders, through a broker called Alpaca.** Alpaca is a modern brokerage
built for bots: instead of clicking "buy" in an app, software sends Alpaca an instruction and
Alpaca executes it on the real stock market. The bot is fully wired to Alpaca — it can place
orders, check the balance, see positions, and emergency-sell everything.

### "Is it trading real money right now?"
**No — right now it's in "paper trading" mode.** "**Paper trading**" = a full simulation using
fake money on a *real* market feed. Alpaca gives you a practice account
(`paper-api.alpaca.markets`) that behaves exactly like the real thing — real prices, real order
mechanics — but the dollars aren't real. The app is currently pointed at this practice account.
**This is the correct and safe place to be right now.**

### "Where is the real trade? Can we even make money here?"
The "real trade" is the order that goes to Alpaca and shows up as a **Position** (a stock you
now hold) with a **P&L** (profit/loss) that moves as the price moves. You see exactly this on
the Overview, Signals, and Command Center pages — it's just currently happening with practice money.

Can it make money? **That's the entire bet of the project, and it's deliberately not been
answered with real cash yet** — because the project has a built-in rule (Ross's "U6") that says:
*the bot must prove itself in simulation first* — at least **10 trading days in a row with ≥60%
winning accuracy** — before it touches a single real dollar. This is the safety gate protecting
the client's money. The bot is *built*; it now needs to *prove itself* in paper trading.

### "Why does it barely seem to do anything / show real trades?"
Two reasons, both intentional:
1. Real Ross setups are *rare* — all 7 gates rarely align. Ross himself passes on most of the
   market most of the time.
2. The demo deliberately **switches off** a couple of features it can't get cheap data for (the
   "E6" deep order-book check and live news for "P5"), so live auto-trades are extra rare. When
   the market's closed (nights/weekends), the dashboard shows a **"REPLAY"** badge — it generates
   *synthetic* (made-up) activity just so the screens aren't blank. That replay data is
   fake-for-display; the practice trades during market hours are the real (paper) thing.

---

# Part 6 — Where the project actually stands

**✅ Built and working:**
- The full pipeline: scanner → strategy → risk manager → execution → journal.
- The complete dashboard (all the pages above).
- A real broker connection (Alpaca, paper mode) — it places practice orders end-to-end.
- The AI catalyst grader and the AI analysis page.
- All the safety guardrails (daily loss limit, 3-strikes, no-overnight, mental stops, etc.).

**⏳ Not yet done / gated (the road to real money):**
1. **Prove it in simulation** — run the 10+ winning sim days the rules require.
2. **Upgrade the data** — the free Alpaca data feed (IEX) isn't good enough for the real thing;
   production needs a paid market-data subscription (~$99/mo), plus real news (Benzinga) and
   deep order-book data (Databento) for the features currently switched off.
3. **Flip the live switch** — a deliberate, manual sign-off (`LIVE_ENABLED=true`) plus pointing
   Alpaca at the real-money endpoint, and starting with tiny position sizes ("capital ramp":
   100 shares, then 2,000, then full) to ease in safely.

> **Bottom line:** a finished, well-architected trading machine sitting in safe practice mode,
> with a clear, rules-based runway to real trading. Nothing is broken or missing in a scary way
> — it's exactly where a responsible build *should* be before risking a client's money.

## Suggested next steps (no coding required)

1. **Run it locally and click around** during US market hours (~9:30am–4pm New York time) so you
   see live paper data, not replay. Steps are in `DEMO_README.md`.
2. **Place one manual paper trade** from the Command Center to watch the full flow (order →
   position → P&L → journal) with your own eyes. Zero risk — practice money.
3. Build comfort, then prepare a client-facing status summary.

---

# Part 7 — A glossary of every term

| Term | Plain-English meaning |
|---|---|
| **Stock / Share / Equity** | A tiny piece of ownership in a company, bought and sold on the market. |
| **Symbol / Ticker** | The short code for a stock (e.g., `AAPL`). |
| **Day trading** | Buy and sell the same day; never hold overnight. |
| **Broker** | The company that places your orders on the market. Here: **Alpaca**. |
| **Paper trading** | A realistic simulation with fake money on a real market feed. |
| **Position** | A stock you currently hold. |
| **P&L** | Profit & Loss — how much money a trade or the day has made or lost. |
| **Unrealized P&L** | Profit/loss *if you sold right now* — not locked in yet. |
| **Realized P&L** | Profit/loss already locked in by selling. |
| **RVOL (Relative Volume)** | Today's trading activity vs. a normal day. 5× = 5 times busier than usual. |
| **Float** | How many shares are available to trade. Low float = bigger, faster moves. |
| **Catalyst** | The breaking news driving a stock's move (Pillar 5). |
| **MACD** | A standard momentum gauge. The bot requires it positive before any entry (E4). |
| **Spread** | The gap between the best buy price and best sell price. A few cents is ideal (E7). |
| **VWAP** | Volume-Weighted Average Price — the day's "center of gravity" for the price. |
| **9 EMA** | A short moving-average line the bot uses to gauge pullback quality. |
| **Pullback** | A small dip after a surge — the "breath" the bot waits to buy into. |
| **Tier A** | The wide net — stocks worth watching but not yet meeting all rules. |
| **Tier B** | Stocks that passed all Five Pillars — the only ones the bot trades. |
| **Five Pillars (P1–P5)** | The five hard stock-picking requirements (price, float, RVOL, +10%, catalyst). |
| **Entry Gates (E1–E7)** | The seven moment-of-entry checks; all must pass to buy. |
| **Conviction** | A confidence score for a setup; higher → bigger allowed size. |
| **Mental Stop** | A stop price kept in the bot's memory (not placed at the exchange) to avoid stop-hunting. |
| **Risk:Reward (2:1)** | Must stand to gain at least twice what you'd lose. |
| **Cushion / Icebreaker size** | Reduced position size used while the day is in the red. |
| **3-Strikes Rule** | 3 losses in a row → stop trading for the day. |
| **Daily Loss Limit** | If today's loss hits this, the bot halts for the day. |
| **Give-back** | How much of peak profit has been handed back; 50% give-back halts trading. |
| **HOT / COLD / REHAB** | The market "mood." HOT = size up; COLD = cautious default; REHAB = tiny size after a big loss. |
| **AUTO_TRADE** | When ON, the bot trades automatically. When OFF, it shows signals but doesn't trade. |
| **Flatten** | Sell everything and go to zero positions immediately. |
| **Kill Switch** | Emergency: halt the bot and flatten all positions at once. |
| **Replay mode** | When the market is closed, the dashboard shows synthetic activity so screens aren't blank. |
| **Alpaca** | The broker (and market-data provider) the bot connects to. |
| **SIP vs IEX** | Two market-data feeds. IEX is free but partial; SIP is paid and complete (needed for production). |

---

# Appendix A — A concrete trade, step by step

A worked example showing the whole pipeline on an imaginary stock "XYZZ." (Illustrative numbers.)

- **7:00 AM ET** — Scanner wakes up, starts Tier A surveillance.
- **7:15 AM** — XYZZ pops 6% pre-market on a 4.2% gap (price $8.50). Added to the watchlist (Tier A).
- **9:25 AM** — XYZZ now up 12%, volume 7.5× normal, float 8.3M shares. News headline: "XYZZ Biotech
  Announces FDA Fast-Track Status." The AI classifier scores it `biotech_fda`, confidence 0.82 →
  **catalyst VERIFIED**. **All Five Pillars now pass** (P1 price ✓, P2 float ✓, P3 RVOL ✓, P4 +12% ✓, P5 catalyst ✓).
- **9:26 & 9:28 AM** — Two pullback attempts, but each dip is too deep (retrace > 50%) → **E5 fails →
  no entry.** The bot waits patiently.
- **9:30 AM** — A clean setup: surge to $9.80, shallow pullback to $9.55 (36% retrace), signal bar closes $9.62.
  **All E1–E7 pass.** Pattern = Micro Pullback (R1). Conviction ≈ 0.875.
- **Risk Manager** — No daily loss yet, not halted, reward:risk is 2:1 (entry $9.62, stop $9.55,
  target $9.79), no existing XYZZ position → **APPROVED.** Sizing shrinks from a raw 14,286 shares
  down to **~1,094 shares** after the cushion cap, conviction multiplier, and day-of-week adjustment.
- **9:32 AM** — Execution places a *limit* order; fills at $9.65. Position open, mental stop at $9.55.
- **9:35 AM** — Price rises to $9.88, then the first red candle closes at $9.84 → **exit rule P6 fires →
  sell all.** Fills ~$9.82.
- **Result** — Realized P&L ≈ (9.82 − 9.65) × 1,094 = **+$186.** Logged to the journal. Day continues.

The lesson: the bot says "no" far more often than "yes," sizes carefully, and exits on the first
sign the move is over.

---

# Appendix B — Technical reference (engine internals)

> For developers. Maps each stage to its source files and exact rules.

## Scanner — `core/scanner/`
- `scanner.py`, `subscanners.py`, `rvol.py`, `float_resolver.py`
- **Two tiers:** Tier A (wide net, ~100–200 names) → Tier B (Five Pillars, all must pass).
- **Five Pillars:** P1 price $2–$20 · P2 float ≤ 20M · P3 RVOL ≥ 5× · P4 ROC ≥ +10% · P5 verified catalyst.
- **Sub-scans:** `top_gainers()`, `low_float_top_gainer()`, `hod_momentum()`, `running_up()`,
  `halt_scan()`, `continuation()`.
- **Attention rank:** top 3 = PRIME, 4–10 = WATCH, outside top 10 = IGNORE.

## Strategy engine — `core/strategy/`
- `engine.py`, `entry_gate.py`, `patterns.py`, `conviction.py`, `exit_engine.py`
- **Entry gates (all AND):** E1 pillars · E2 pullback · E3 candle-over-candle new high · E4 MACD
  positive · E5 retrace ≤ 50% (preferred ≤ 25%) · E6 L2/tape support · E7 spread 3–10¢.
- **Patterns & base conviction:** R1 Micro Pullback (highest) · R2 ABCD (0.85) · R3 Bull Flag
  (0.80) · R5 Gap-and-Go (0.70) · R6 VWAP Break (0.65) · R7 Halt Resumption (0.60).
- **Conviction score** (weighted, clamped 0.25–1.0): pattern 30% · RVOL 25% · float 15% ·
  attention 15% · spread 8% · retrace 7%. Bonus +0.05 (9 EMA touch), +0.03 (above VWAP).

## Risk Manager — `core/risk/`
- `manager.py`, `pre_trade.py`, `sizing.py`, `monitors.py`
- **Pre-trade vetoes:** U1 pillars confirmed · 2:1 reward:risk · U4 daily loss · U4 give-back
  (50% of peak) · U5 three strikes · U2 no averaging down · PDT guard · U15 skip-list catalyst ·
  time gate (after `HARD_STOP_TIME`).
- **Sizing chain:** raw (risk-formula `$risk / (entry − stop)` or flat-block) → cushion cap (¼ max
  while red) → × conviction → day-of-week × → market-state cap (HOT/COLD/REHAB) → liquidity cap
  (~1% ADV) → `MAX_SIZE` ceiling.

## Exit engine — `core/strategy/exit_engine.py`
Eight prioritized rules; first match wins:
- **P1** Hard stop (mental) · **P2** Breakout-or-bailout (time stop) · **P3** L2/tape reversal ·
  **P4** Topping tail · **P5** Scale into strength (sell half, stop → breakeven) · **P6** First
  red candle close · **P7** VWAP guard · **P8** Lost popularity (out of top 10).

## AI components
- **Catalyst classifier** — `adapters/catalyst/llm_classifier.py`, `provider.py`. 5-layer defense:
  reaction-proof gate → SEC EDGAR dilution check → fetch headlines → keyword SKIP scan → LLM
  (Claude Haiku 4.5). Verdict: VERIFIED / SKIP / UNVERIFIED (default = no trade).
- **Market-state classifier** — `adapters/market_state/classifier.py`. Reads 3 rolling metrics
  (count of 100%+ gainers, gapper follow-through rate, average winner size) → HOT / COLD / REHAB.
  Biases COLD when uncertain or with < 10 days of history.

---

# Appendix C — Technical reference (backend API)

> The FastAPI backend (`api/`) serves the dashboard. In the demo it is driven by a **demo engine**
> (`core/demo/`) that runs the real strategy loop against live Alpaca paper data (or synthetic
> replay when the market is closed / no keys).

## Endpoint groups

**Dashboard (`/api`, GET, read-safe):**
`GET /api/state` (full snapshot) · `/api/watchlist` · `/api/positions` · `/api/signals` ·
`/api/risk-events` · `/api/journal`.

**Operator console (`/api`, GET + authed POST):**
`GET /api/bars/{symbol}` · `POST /api/scanner/trigger` · `GET /api/models` · `GET /api/account` ·
`GET /api/analyze/{symbol}` · `POST /api/positions/{symbol}/close` · `.../scale-out` · `.../stop` ·
`POST /api/trade/manual` · `POST /api/trade/manual-order` · `GET/PATCH /api/config` ·
`POST /api/control/flatten | pause | resume | halt-day` ·
`GET /api/journal/today | session-summary | export`.

**Controls (`/controls`, POST, requires API key):**
`POST /controls/kill-switch` (halt + flatten all) · `/controls/pause` · `/controls/resume`.

**Health (`/health`):** `GET /health/` (feed liveness, clock drift, order-ack latency) ·
`GET /health/ready` (readiness probe) · `GET /` (liveness).

**WebSocket:** `WS /ws/live` — pushes a full snapshot on connect, then streams every mutation
(watchlist, signals, risk events, health) in real time.

## What is real vs. simulated

| Component | Real or simulated | Notes |
|---|---|---|
| Market-data feed | REAL (Alpaca IEX) if keys, else synthetic replay | Free IEX feed; SIP needed for production |
| Broker connection | REAL (Alpaca **paper**) if keys, else idle | Paper only; no live-money endpoint in demo |
| Watchlist scanning | REAL algorithmic gates on live data | Five Pillars minus catalyst |
| Entry signals | REAL gate evaluation | MACD, spread, retrace |
| Risk gates | REAL enforcement | Halts, pauses, daily-loss, 3-strikes |
| Order submission | REAL to Alpaca paper | Limit-only with offset |
| Position tracking | REAL from Alpaca account | Mental stops tracked locally |
| Mental stops (U13) | Local (not resting broker orders) | Exit monitor polls price |
| L2 depth (E6) | STUBBED / bypassed | Alpaca free tier has no depth-of-book |
| News catalyst (P5) | STUBBED in demo | No licensed news feed wired in demo |
| Replay mode | SYNTHETIC when market closed | Clearly labelled "REPLAY" in the UI |

## What blocks real-money trading today
1. `LIVE_ENABLED=false` (must be manually set in the config DB).
2. Simulator gate U6 not satisfied (needs ≥ 10 consecutive sim days ≥ 60% accuracy).
3. Alpaca pointed at the paper endpoint by design.
4. Data feed is IEX (free), not SIP (paid) — fails the production scan requirement.
5. Catalyst (P5) and L2 (E6) providers are stubbed → fail-closed (safe).

---

*Generated as an onboarding guide for RossBot. Source of truth for strategy rules remains
`ROSSBOT_STRATEGY_SPEC.md`; build phases in `ROSSBOT_PROJECT_PLAN.md`; the working contract in
`CLAUDE.md`.*
