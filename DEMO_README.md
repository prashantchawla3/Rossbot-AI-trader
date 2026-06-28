# RossBot — Demo Operator Guide (Alpaca Paper Trading)

End-to-end demo: **Market Data → Scanner → Strategy → Paper Execution → Dashboard**, all on
Alpaca **paper** trading (no real money). The trading loop runs inside the FastAPI process and
pushes live state to the Next.js dashboard over WebSocket.

> ⚠️ **Demo simplifications (shown in the UI):** E6/Level-2 support gate is **bypassed** (Alpaca
> has no depth-of-book); Pillar-5 catalyst is **not verified** (float comes from a hard-coded
> lookup; UNKNOWN-float names are excluded from Tier B); the free **IEX** feed is used; the
> market-state is forced **HOT**. None of these weaken the production guardrails (U1–U15).

---

## 1. One-time setup

```powershell
# from the project root
python -m venv .venv                       # (already created)
.venv\Scripts\activate
pip install -r requirements.txt            # includes alpaca-py
cd dashboard && npm install && cd ..       # (node_modules already present)
```

## 2. Get free Alpaca paper keys (required for live trading/positions)

1. Sign up free at **https://alpaca.markets**.
2. Switch to **Paper Trading** (toggle, top-left).
3. **Generate API Keys** → copy the **API Key ID** and **Secret Key**.
4. Put them in the project-root **`.env`**:

```
ALPACA_API_KEY=<your paper key id>
ALPACA_SECRET_KEY=<your paper secret>
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_URL=https://data.alpaca.markets
ALPACA_DATA_FEED=iex          # free; use "sip" only with an Algo Trader Plus sub
```

> Without keys the system still boots and the dashboard stays alive via **replay mode** —
> it just won't place real paper orders or show real positions.

The dashboard talks to the API using `DASHBOARD_API_KEY` (default `rossbot-demo-key`, already set
in `.env` and `dashboard/.env.local` — keep them matching).

## 3. Start everything

```bash
./start.sh            # Git Bash / macOS / Linux
```
or on Windows:
```bat
start.bat
```

This launches:
- **API** → http://localhost:8000  (trading loop runs in-process)
- **Dashboard** → http://localhost:3000

## 4. Verify (demo checklist)

```powershell
# broker connectivity + account (real data once keys are set)
.venv\Scripts\python.exe -c "import asyncio; from dotenv import load_dotenv; load_dotenv(); from core.demo.config import DemoConfig; from core.demo.engine import DemoEngine; from core.demo.state import DemoDashboardState; e=DemoEngine(DemoConfig.from_env(), DemoDashboardState()); e.connect(); print(asyncio.run(e.verify_broker()))"

# API health / state / watchlist (no 500s; data within ~60s)
curl http://localhost:8000/health
curl http://localhost:8000/api/state
curl http://localhost:8000/api/watchlist

# inject a manual test signal → appears in the dashboard Signals feed
curl -X POST "http://localhost:8000/api/demo/test-signal?symbol=DEMO"

# controls (need the API key header)
curl -X POST http://localhost:8000/controls/pause       -H "X-API-Key: rossbot-demo-key"
curl -X POST http://localhost:8000/controls/resume      -H "X-API-Key: rossbot-demo-key"
curl -X POST http://localhost:8000/controls/kill-switch -H "X-API-Key: rossbot-demo-key"   # halt + flatten all
```

Dashboard panels: **Watchlist** (Tier A/B, price, RVOL, float/UNKNOWN, pillar flags),
**Signals** (E1–E7 gate breakdown, conviction colour), **Positions** (live P&L),
**Risk** (day P&L, consecutive losses, status), **Health** (feed/broker, session, ET clock),
**Controls** (Pause / Resume / Kill-Switch).

## 5. Demo behaviour by time of day

| Market state (ET)        | What you see                                                        |
|--------------------------|---------------------------------------------------------------------|
| Closed (nights/weekends) | **Replay mode** — synthetic watchlist + signals so the UI is alive  |
| Pre-market / RTH / AH     | **Live** snapshots populate the watchlist from real gainers         |
| 07:00–11:00 ET + AUTO_TRADE | New paper entries are allowed when E1–E7 + risk gate pass         |

Live E1–E7 entries are intentionally **rare** (real pullback-and-go pattern). For a guaranteed
on-screen signal during the demo, use the **test-signal** endpoint above.

## 6. Demo tuning knobs (`.env`)

`AUTO_TRADE` (place orders vs signal-only) · `MAX_DAILY_LOSS` (shutdown floor, default $500) ·
`MAX_POSITION_SIZE` (share cap) · `PER_TRADE_RISK` ($ risk budget) · `HARD_STOP_TIME` ·
`MARKET_STATE` · `DEMO_REPLAY_MODE` · `E6_ENABLED` · `SCAN_INTERVAL_S` / `STRATEGY_INTERVAL_S` /
`EXIT_INTERVAL_S` · `ROSSBOT_RUN_ENGINE` (set `false` to run the dashboard API without the loop).
