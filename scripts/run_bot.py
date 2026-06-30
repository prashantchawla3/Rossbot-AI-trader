#!/usr/bin/env python
"""
RossBot terminal runner — runs the paper-trading engine directly in your terminal.

No dashboard or browser needed. Shows real-time activity as the bot:
  • scans ~115 symbols every 60 s for momentum setups
  • applies the Five Pillars gate (price, float, RVOL, ROC, catalyst)
  • runs the E1–E7 entry gate on every Tier-B candidate
  • places paper orders via Alpaca when auto-trade is ON (07:00–11:00 ET only)
  • monitors open positions and exits via hard-stop / time-stop / scale-out

Usage:
    python scripts/run_bot.py              full paper-trading mode
    python scripts/run_bot.py --no-trade   signal-only, no orders placed

Press Ctrl+C to stop and view session results.

Requirements:
    .env file with ALPACA_API_KEY and ALPACA_SECRET_KEY
    (get free paper keys: https://alpaca.markets → Paper Trading → API Keys)
    .venv with deps: pip install -e ".[vendors]"

Trading entries only accepted 07:00–11:00 ET on weekdays (spec §7).
Outside that window the bot scans but skips new positions.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time as _time_mod
from datetime import time as _time
from decimal import Decimal
from pathlib import Path
from typing import Any

# ── repo root on sys.path ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before importing project modules so config picks up credentials.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

# Silence structlog / engine internals — ConsoleDashboardState surfaces events.
logging.basicConfig(level=logging.CRITICAL)

# ── project imports ───────────────────────────────────────────────────────────
from core.demo.config import DemoConfig
from core.demo.engine import DemoEngine
from core.demo.state import DemoDashboardState
from core.timeutils import Session, et_time, now_utc, session_for

# ── ANSI colours ──────────────────────────────────────────────────────────────
_G  = "\033[92m"   # green
_Y  = "\033[93m"   # yellow
_R  = "\033[91m"   # red
_C  = "\033[96m"   # cyan
_BO = "\033[1m"    # bold
_DI = "\033[2m"    # dim
_RS = "\033[0m"    # reset


def _green(t: str) -> str:  return f"{_G}{t}{_RS}"
def _yellow(t: str) -> str: return f"{_Y}{t}{_RS}"
def _red(t: str) -> str:    return f"{_R}{t}{_RS}"
def _cyan(t: str) -> str:   return f"{_C}{t}{_RS}"
def _bold(t: str) -> str:   return f"{_BO}{t}{_RS}"
def _dim(t: str) -> str:    return f"{_DI}{t}{_RS}"


# ── dedup state for veto spam suppression ─────────────────────────────────────
_last_veto: str | None = None
_veto_count: int = 0


# ── output helpers ────────────────────────────────────────────────────────────

def _ts() -> str:
    return et_time(now_utc()).strftime("%H:%M:%S")


def _sep(char: str = "─", width: int = 64) -> None:
    print(_dim(f"  {char * width}"))


def _log(title: str, *lines: str, color: str = _RS) -> None:
    ts = _ts()
    heading = f"{color}{title}{_RS}" if color != _RS else _bold(title)
    print(f"\n  {_dim(f'[{ts}]')} {heading}")
    for ln in lines:
        if ln:
            print(f"            {ln}")


# ── event printers ────────────────────────────────────────────────────────────

def _print_scan(count: int, tier_a: list[dict[str, Any]], tier_b: list[dict[str, Any]]) -> None:
    is_replay = any("REPLAY" in str(e.get("catalyst", "")) for e in tier_a)
    tag = _dim(" [REPLAY — market closed, synthetic data]") if is_replay else ""

    if not tier_a:
        _log(f"SCAN #{count}{tag}  —  no Tier-A movers", color=_DI)
        return

    tier_b_syms = {e.get("symbol", "") for e in tier_b}
    title_color = _DI if is_replay else _C
    _log(
        f"SCAN #{count}{tag}",
        f"{_bold('Tier-A')} ({len(tier_a)} movers)   "
        + (_green(_bold(f"Tier-B ({len(tier_b)})")) if tier_b else _dim(f"Tier-B (0)")),
        color=title_color,
    )

    for e in tier_a[:6]:
        sym      = e.get("symbol", "?")
        price    = e.get("price", "?")
        chg      = e.get("change_pct", "?")
        rvol     = e.get("rvol", "?")
        flt      = e.get("float_shares")
        flt_str  = f"{flt / 1_000_000:.1f}M" if flt else "—"
        cat      = str(e.get("catalyst", ""))
        is_b     = sym in tier_b_syms

        if "VERIFIED" in cat and "SKIP" not in cat:
            cat_str = _green("✓ catalyst")
        elif "SKIP" in cat:
            cat_str = _red("✗ skip")
        else:
            cat_str = _dim("unverified")

        b_tag    = _green("  ← Tier-B ✓") if is_b else ""
        sym_disp = _green(_bold(sym)) if is_b else _bold(sym)

        print(f"            {sym_disp:<16}  +{chg}%  ${price:<7}  "
              f"RVOL {rvol}x  float {flt_str:<7}  {cat_str}{b_tag}")

    if len(tier_a) > 6:
        print(f"            {_dim(f'... and {len(tier_a) - 6} more')}")


def _print_signal(sig: dict[str, Any]) -> None:
    global _last_veto, _veto_count

    action = sig.get("action", "")
    etype  = sig.get("event_type", "")
    sym    = sig.get("symbol", "?")
    detail = sig.get("detail", {})
    conv   = sig.get("conviction")

    # ── entry approved ────────────────────────────────────────────────────────
    if action == "entry" and etype == "entry_signal":
        if detail.get("mode") == "REPLAY":
            return  # replay signals are synthetic, not worth printing every tick

        gates = detail.get("gates", {})
        gate_parts = []
        for k, v in gates.items():
            lbl = k.split("_")[0]        # E1, E2 …
            gate_parts.append((_green if v else _dim)(lbl))

        entry  = detail.get("entry", "?")
        stop   = detail.get("stop",  "?")
        target = detail.get("target","?")
        spread = detail.get("spread","?")
        shares = detail.get("shares")
        conv_s = f"  conviction {conv:.0%}" if conv else ""
        shares_s = f"  shares: {_bold(str(shares))}" if shares else ""

        _log(
            f"STRATEGY APPROVED  →  {_bold(sym)}",
            f"Gates: {' '.join(gate_parts)}",
            f"Entry ${entry}   Stop ${stop}   Target ${target}   Spread ${spread}{conv_s}",
            f"Risk gate: {_green('APPROVED')}{shares_s}",
            color=_C,
        )
        _last_veto = None
        _veto_count = 0

    # ── veto ──────────────────────────────────────────────────────────────────
    elif action == "veto":
        veto = detail.get("veto", "?")
        if veto == _last_veto:
            _veto_count += 1
            # Print every 10th repeat so repeated vetoes don't fill the screen
            if _veto_count % 10 == 0:
                print(f"  {_dim(f'[{_ts()}]')} {_dim(f'VETO {sym}: {veto}  (×{_veto_count})')}",
                      flush=True)
        else:
            _last_veto = veto
            _veto_count = 1
            _log(f"VETO  {sym}  —  {veto}", color=_DI)

    # ── exit ──────────────────────────────────────────────────────────────────
    elif action == "exit":
        reason   = detail.get("reason", etype)
        pnl_raw  = detail.get("pnl", "")
        shares   = detail.get("shares", detail.get("remaining_shares", ""))
        pnl_disp = ""
        pnl_val: Decimal | None = None
        if pnl_raw:
            try:
                pnl_val = Decimal(pnl_raw)
                pnl_disp = _green(f"+${pnl_val:.2f}") if pnl_val > 0 else _red(f"-${abs(pnl_val):.2f}")
            except Exception:
                pnl_disp = pnl_raw
        color = _G if (pnl_val or 0) > 0 else (_R if (pnl_val or 0) < 0 else _Y)
        shares_s = f"  shares: {shares}" if shares else ""
        _log(
            f"EXIT  →  {_bold(sym)}  [{reason}]",
            f"P&L: {pnl_disp}{shares_s}" if pnl_disp else "",
            color=color,
        )


def _print_risk_event(ev: dict[str, Any]) -> None:
    etype  = ev.get("event_type", "")
    sev    = ev.get("severity", "INFO")
    msg    = ev.get("message", "")
    detail = ev.get("detail", {})

    if etype == "ORDER":
        ack = str(detail.get("ack", ""))
        ok  = ack.lower() in ("accepted", "pending_new", "new", "filled", "partially_filled")
        status = _green("✓ accepted") if ok else _yellow(f"? {ack}")
        _log(f"ORDER  →  {_bold(msg)}", f"Status: {status}", color=_G)

    elif etype == "ORDER_REJECT":
        _log(f"ORDER REJECTED  →  {msg}", color=_Y)

    elif etype in ("EXIT", "MANUAL_EXIT"):
        pnl_raw = detail.get("pnl", "")
        reason  = detail.get("reason", "")
        pnl_val: Decimal | None = None
        pnl_s = ""
        if pnl_raw:
            try:
                pnl_val = Decimal(pnl_raw)
                pnl_s = _green(f"+${pnl_val:.2f}") if pnl_val > 0 else _red(f"-${abs(pnl_val):.2f}")
            except Exception:
                pnl_s = pnl_raw
        color = _G if (pnl_val or 0) > 0 else (_R if (pnl_val or 0) < 0 else _RS)
        _log(f"CLOSED  →  {msg}", f"P&L: {pnl_s}  [{reason}]" if pnl_s else "", color=color)

    elif etype == "FLATTEN":
        _log(f"FLATTEN ALL  →  {msg}", color=_R)

    elif etype == "INFO" and sev == "INFO":
        _log(f"  {msg}", color=_DI)

    elif sev == "CRITICAL":
        _log(f"⚠  {msg}", color=_R)

    elif sev == "WARN" and etype not in ("VETO", "CONFIG_OVERRIDE"):
        _log(f"⚠  {msg}", color=_Y)


def _print_status(engine: DemoEngine) -> None:
    risk     = engine.risk
    n_pos    = len(engine.positions)
    pnl      = risk.realized_pnl
    pnl_s    = _green(f"+${pnl:.2f}") if pnl > 0 else (_red(f"-${abs(pnl):.2f}") if pnl < 0 else "$0.00")
    sess     = session_for(now_utc())
    et_str   = et_time(now_utc()).strftime("%H:%M:%S")

    _sep()
    print(f"  STATUS  |  {_bold(str(sess))}  ET {et_str}")
    print(f"  P&L today: {pnl_s}   "
          f"Trades: {risk.trades_today}  ({risk.wins_today}W {risk.losses_today}L)   "
          f"Open positions: {n_pos}")
    if risk.consecutive_losses:
        print(f"  {_yellow(f'Warning: {risk.consecutive_losses} consecutive losses')}")
    if risk.halted:
        print(f"  {_red(f'HALTED: {risk.halt_reason}')}")
    _sep()


def _print_summary(engine: DemoEngine) -> None:
    print()
    _sep("═", 64)
    print(f"  {_bold('SESSION SUMMARY')}")
    _sep("═", 64)

    summary = engine.session_summary()
    risk    = engine.risk
    pnl     = risk.realized_pnl
    pnl_s   = _green(f"+${pnl:.2f}") if pnl > 0 else (_red(f"-${abs(pnl):.2f}") if pnl < 0 else _dim("$0.00"))

    print(f"  Realized P&L:    {pnl_s}")
    print(f"  Trades:          {summary['trades']}   ({summary['wins']}W  {summary['losses']}L)")

    wr = summary.get("win_rate")
    if wr is not None:
        print(f"  Win rate:        {wr:.0%}")

    if summary["trades"] > 0:
        print(f"  Avg winner:      {_green(str(summary.get('avg_winner', '0.00')))}")
        print(f"  Avg loser:       {_red(str(summary.get('avg_loser', '0.00')))}")
        pf = summary.get("profit_factor")
        if pf is not None:
            print(f"  Profit factor:   {pf:.2f}")
        print(f"  Best trade:      {_green(str(summary.get('best_trade', '0.00')))}")
        print(f"  Worst trade:     {_red(str(summary.get('worst_trade', '0.00')))}")

    # Closed trade table
    trades = engine.journal_today()
    if trades:
        _sep()
        print(f"  {'SYM':<6}  {'ENTRY':>7}  {'EXIT':>7}  {'SHARES':>6}  {'P&L':>9}  REASON")
        _sep()
        for t in trades:
            pnl_t = Decimal(t["pnl"])
            pnl_t_s = _green(f"+${pnl_t:.2f}") if pnl_t > 0 else _red(f"-${abs(pnl_t):.2f}")
            print(f"  {t['symbol']:<6}  ${t['entry_price']:>6}  ${t['exit_price']:>6}  "
                  f"{t['shares']:>6}  {pnl_t_s:>14}  {_dim(t.get('exit_reason', ''))}")

    if not trades:
        print(f"\n  {_dim('No trades completed this session.')}")
        sess = session_for(now_utc())
        if str(sess) == "CLOSED":
            print(f"  {_dim('Market was closed — bot ran in REPLAY mode (synthetic data).')}")
        else:
            et_h = et_time(now_utc()).hour
            if et_h >= 11:
                print(f"  {_dim('Entry window (07:00–11:00 ET) had already closed.')}")
            else:
                print(f"  {_dim('No setups passed all Five Pillars + E1–E7 gates.')}")

    _sep("═", 64)
    print()


# ── console dashboard state ───────────────────────────────────────────────────

class ConsoleDashboardState(DemoDashboardState):
    """Routes engine events to the terminal instead of a WebSocket."""

    def __init__(self) -> None:
        self._scan_count = 0
        self._last_replay_print: float = 0.0
        super().__init__(broadcast=self._on_event)

    async def _on_event(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        payload = msg.get("payload", {})
        if mtype == "signal":
            _print_signal(payload)
        elif mtype == "risk_event":
            _print_risk_event(payload)
        # "state_update" → silently ignored (no WebSocket subscriber)

    async def update_watchlists(
        self,
        tier_a: list[dict[str, Any]],
        tier_b: list[dict[str, Any]],
    ) -> None:
        self._scan_count += 1
        is_replay = any("REPLAY" in str(e.get("catalyst", "")) for e in tier_a)
        now_t = _time_mod.monotonic()

        if is_replay and (now_t - self._last_replay_print) < 60:
            # Replay fires every 5 s — only print once per minute.
            async with self._lock:
                self._tier_a = list(tier_a)
                self._tier_b = list(tier_b)
            return

        if is_replay:
            self._last_replay_print = now_t

        _print_scan(self._scan_count, tier_a, tier_b)
        await super().update_watchlists(tier_a, tier_b)


# ── main ─────────────────────────────────────────────────────────────────────

async def _main(no_trade: bool) -> None:
    if no_trade:
        os.environ["AUTO_TRADE"] = "false"

    cfg = DemoConfig.from_env()

    # ── startup banner ────────────────────────────────────────────────────────
    print()
    _sep("═", 64)
    print(f"  {_bold('RossBot  —  Paper Trading Terminal')}")
    _sep("═", 64)
    print()

    now  = now_utc()
    sess = session_for(now)
    et   = et_time(now)
    in_window = _time(7, 0) <= et <= _time(11, 0) and str(sess) != "CLOSED"

    print(f"  {'Mode:':<22} PAPER  (Alpaca paper trading)")
    print(f"  {'Market session:':<22} {_bold(str(sess))}  {et.strftime('%H:%M ET')}")
    print(f"  {'Entry window:':<22} 07:00–11:00 ET  "
          + (_green("OPEN") if in_window else _yellow("currently outside")))
    print(f"  {'Auto-trade:':<22} "
          + (_green("ON  (will place paper orders)") if cfg.auto_trade
             else _yellow("OFF  (signal-only, no orders)")))
    print(f"  {'Max daily loss:':<22} ${cfg.max_daily_loss:.0f}")
    print(f"  {'Per-trade risk:':<22} ${cfg.per_trade_risk:.0f}")
    print(f"  {'Scan interval:':<22} {cfg.scan_interval_s}s")

    if not cfg.has_credentials:
        print()
        print(f"  {_yellow('⚠  No Alpaca credentials found in .env')}")
        print(f"     Set ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        print(f"     Get free paper keys: https://alpaca.markets  → Paper Trading → API Keys")
        print(f"     {_dim('Running in offline REPLAY mode until credentials are added.')}")

    if str(sess) == "CLOSED":
        print()
        print(f"  {_dim('Market is CLOSED → bot will run in REPLAY mode (synthetic data).')}")
        print(f"  {_dim('Real scans and trades begin at 07:00 ET on the next trading day.')}")
    elif not in_window:
        print()
        if et < _time(7, 0):
            print(f"  {_dim('Before entry window — scanning starts at 07:00 ET.')}")
        else:
            print(f"  {_dim('Entry window (07:00–11:00 ET) has closed for today.')}")
            print(f"  {_dim('Scans will run but no new positions will be opened.')}")

    print()
    _sep()
    print(f"  {_dim('Press Ctrl+C to stop and view the session summary.')}")
    _sep()

    # ── engine ────────────────────────────────────────────────────────────────
    state  = ConsoleDashboardState()
    engine = DemoEngine(cfg, state)
    engine.set_control_hooks(lambda: False, lambda: False)
    engine.connect()

    _stop = asyncio.Event()

    async def _heartbeat() -> None:
        await asyncio.sleep(300)        # first heartbeat after 5 min
        while not _stop.is_set():
            _print_status(engine)
            try:
                await asyncio.wait_for(_stop.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass

    hb = asyncio.create_task(_heartbeat())

    try:
        await engine.run()
    except asyncio.CancelledError:
        pass
    finally:
        _stop.set()
        hb.cancel()
        try:
            await hb
        except (asyncio.CancelledError, Exception):
            pass
        _print_summary(engine)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python scripts/run_bot.py",
        description="RossBot terminal runner — paper trades in the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--no-trade",
        action="store_true",
        help="Signal-only mode: scan and generate signals but do not submit any orders.",
    )
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task: asyncio.Task | None = None  # type: ignore[type-arg]

    def _cancel() -> None:
        if task and not task.done():
            task.cancel()

    try:
        import signal as _signal
        loop.add_signal_handler(_signal.SIGINT,  _cancel)
        loop.add_signal_handler(_signal.SIGTERM, _cancel)
    except (NotImplementedError, AttributeError):
        pass  # Windows: handled via KeyboardInterrupt below

    try:
        task = loop.create_task(_main(args.no_trade))
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        print()
        if task and not task.done():
            task.cancel()
            try:
                loop.run_until_complete(task)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
