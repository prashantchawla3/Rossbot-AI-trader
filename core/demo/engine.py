"""DemoEngine — the end-to-end paper-trading loop for the demonstration.

Pipeline (spec-traced, demo-simplified):
  snapshot universe → Tier-A wide net (§1) → Tier-B Five-Pillars gate (§1)
    → entry gate E1–E7 (§2, E6 BYPASSED — no Alpaca L2) → demo risk gate (§5)
    → Alpaca paper order (§10 limit+offset) → exit monitor P1/P2/P4/P5/P6 (§3)
    → push positions/risk/signals to the dashboard (WebSocket + REST).

DEMO SIMPLIFICATIONS (all surfaced in the UI):
  - E6 (L2 support) is bypassed: Alpaca has no native depth-of-book.
  - Pillar-5 catalyst is not verified (no licensed news feed); float comes from a
    hard-coded lookup. Symbols with UNKNOWN float are excluded from Tier B.
  - MARKET_STATE forced HOT so the demo shows activity.
  - Mental-stop monitor polls every few seconds (not the sub-second live path).

Runs inside the FastAPI process so it shares the WebSocket manager and respects
the dashboard kill-switch / pause controls (it reads the StateService flags).
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from adapters.alpaca import AlpacaMarketDataAdapter
from adapters.alpaca_broker import AlpacaBrokerAdapter
from adapters.base import OrderRequest, Side
from core.demo.config import DemoConfig
from core.demo.state import DemoDashboardState, _s
from core.demo.universe import STARTER_UNIVERSE, float_for
from core.indicators import macd, macd_positive
from core.timeutils import Session, et_time, now_utc, session_for

log = logging.getLogger(__name__)

# Demo gate constants (spec-traced; mirror core.config defaults but kept local so the
# demo runs with no database).
TIER_A_CHANGE_MIN = Decimal("4")     # §1 TIER_A wide net
TIER_A_PRICE_MIN = Decimal("1")
TIER_A_PRICE_MAX = Decimal("20")
TIER_B_CHANGE_MIN = Decimal("10")    # §1 Pillar-4 ROC
TIER_B_PRICE_MIN = Decimal("2")      # §1 Pillar-1
TIER_B_PRICE_MAX = Decimal("20")
TIER_B_FLOAT_MAX = 20_000_000        # §1 Pillar-2
TIER_B_RVOL_MIN = Decimal("5")       # §1 Pillar-3
SPREAD_MIN = Decimal("0.03")         # §2 E7
SPREAD_MAX = Decimal("0.10")
BUY_OFFSET = Decimal("0.05")         # §10
RETRACE_MAX = Decimal("0.50")        # §2 E5 / C9
BAILOUT_SECONDS = 60                 # §3 P2
BAILOUT_MOVE = Decimal("0.10")       # §3 P2
SCALE_PROFIT_PCT = Decimal("0.05")   # §3 P5 (5%)


@dataclass
class DemoPosition:
    symbol: str
    shares: int
    entry_price: Decimal
    stop_price: Decimal
    entry_time: datetime
    scaled: bool = False


@dataclass
class DemoRisk:
    """Simplified daily risk state for the demo (spec §5)."""

    realized_pnl: Decimal = Decimal("0")
    peak_pnl: Decimal = Decimal("0")
    consecutive_losses: int = 0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    halted: bool = False
    halt_reason: str | None = None

    def record_close(self, pnl: Decimal) -> None:
        self.realized_pnl += pnl
        self.peak_pnl = max(self.peak_pnl, self.realized_pnl)
        if pnl > 0:
            self.wins_today += 1
            self.consecutive_losses = 0
        else:
            self.losses_today += 1
            self.consecutive_losses += 1


@dataclass
class _GateResult:
    passes: bool
    flags: dict[str, bool]
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    reasons: list[str] = field(default_factory=list)


class DemoEngine:
    def __init__(
        self,
        cfg: DemoConfig,
        state: DemoDashboardState,
        *,
        connection_count: Any = None,
    ) -> None:
        self.cfg = cfg
        self.state = state
        # callable returning current ws client count (ws_manager.connection_count)
        self._connection_count = connection_count

        self.broker: AlpacaBrokerAdapter | None = None
        self.data: AlpacaMarketDataAdapter | None = None

        self.risk = DemoRisk()
        self.positions: dict[str, DemoPosition] = {}
        # Completed trades for the session journal (Tab 5). Each: dict with entry/exit/pnl/reason.
        self.closed_trades: list[dict[str, Any]] = []

        self._paused_getter = lambda: False
        self._halted_getter = lambda: False

        self._last_scan_tier_a: list[dict[str, Any]] = []
        self._last_scan_tier_b: list[dict[str, Any]] = []
        self._broker_connected = False
        self._last_data_ts: datetime | None = None
        self._running = False
        self._replay_tick = 0

        # Audited session-config overrides (operator console). U11 is relaxed ONLY for
        # these four keys, and EVERY change writes a risk_event audit row + a spec note.
        # See ROSSBOT_STRATEGY_SPEC.md Appendix A (U11 dashboard-override exception).
        # Keys: AUTO_TRADE (bool), MARKET_STATE (str), MAX_DAILY_LOSS (Decimal), SCAN_INTERVAL (int s)
        self.session_overrides: dict[str, Any] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def set_control_hooks(self, paused_getter: Any, halted_getter: Any) -> None:
        """Wire dashboard pause/kill flags (read each loop)."""
        self._paused_getter = paused_getter
        self._halted_getter = halted_getter

    # ── effective config (session overrides ▸ DemoConfig) ────────────────────────
    # These read the audited session override first, then fall back to the frozen
    # DemoConfig. Only the four U11-exception keys are overridable (see __init__).

    @property
    def effective_auto_trade(self) -> bool:
        return bool(self.session_overrides.get("AUTO_TRADE", self.cfg.auto_trade))

    @property
    def effective_market_state(self) -> str:
        return str(self.session_overrides.get("MARKET_STATE", self.cfg.market_state))

    @property
    def effective_max_daily_loss(self) -> Decimal:
        return self.session_overrides.get("MAX_DAILY_LOSS", self.cfg.max_daily_loss)

    @property
    def effective_scan_interval_s(self) -> int:
        return int(self.session_overrides.get("SCAN_INTERVAL", self.cfg.scan_interval_s))

    def connect(self) -> None:
        """Construct Alpaca adapters. No network call yet (lazy SDK)."""
        if not self.cfg.has_credentials:
            log.warning("demo_engine.no_alpaca_credentials")
            return
        self.broker = AlpacaBrokerAdapter(
            self.cfg.alpaca_api_key,
            self.cfg.alpaca_secret_key,
            paper=self.cfg.paper,
        )
        self.data = AlpacaMarketDataAdapter(
            self.cfg.alpaca_api_key,
            self.cfg.alpaca_secret_key,
            feed=self.cfg.alpaca_data_feed,
            require_sip=False,  # DEMO: IEX free feed; flagged in UI
        )

    async def verify_broker(self) -> dict[str, Any]:
        """Ping the broker once at startup; returns account dict or error info."""
        if self.broker is None:
            return {"connected": False, "error": "no_credentials"}
        try:
            acct = await self.broker.account_state()
            # account_state() fail-safes to zeros on an auth/API error (it never raises),
            # so a funded paper account (equity/buying-power > 0) is the connectivity proof.
            connected = acct.equity > 0 or acct.buying_power > 0
            self._broker_connected = connected
            result: dict[str, Any] = {
                "connected": connected,
                "equity": _s(acct.equity),
                "buying_power": _s(acct.buying_power),
                "cash": _s(acct.cash),
                "day_trade_count": acct.day_trade_count,
            }
            if not connected:
                result["error"] = "account equity/buying-power is 0 — check ALPACA keys/permissions"
            return result
        except Exception as exc:  # noqa: BLE001
            self._broker_connected = False
            return {"connected": False, "error": str(exc)}

    async def run(self) -> None:
        """Main loop. Cadence driven by a 5-second base tick."""
        self._running = True
        base_tick = 5
        strat_every = max(1, self.cfg.strategy_interval_s // base_tick)
        tick = 0
        # Startup banner
        info = await self.verify_broker()
        log.info("demo_engine.start broker=%s", info)
        await self._emit_info(f"Demo engine started (broker connected={info.get('connected')})")

        while self._running:
            try:
                # scan cadence honours the live SCAN_INTERVAL override each loop (U11 exception)
                scan_every = max(1, self.effective_scan_interval_s // base_tick)
                await self._iteration(tick, scan_every, strat_every)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("demo_engine.iteration_error")
            tick += 1
            await asyncio.sleep(base_tick)

    def stop(self) -> None:
        self._running = False

    # ── one iteration ──────────────────────────────────────────────────────────

    async def _iteration(self, tick: int, scan_every: int, strat_every: int) -> None:
        now = now_utc()
        sess = session_for(now)
        market_active = sess in (Session.PREMARKET, Session.RTH, Session.AFTERHOURS)

        if self.data is None or not market_active:
            # No live data (closed market or no creds) → replay keeps the UI alive.
            if self.cfg.demo_replay_mode:
                await self._replay_step()
            await self._sync_positions_and_risk(now)
            await self._push_health(now, sess, market_active)
            return

        # Live path
        if tick % scan_every == 0:
            await self._run_scan(now)
        if tick % strat_every == 0:
            await self._run_strategy(now, sess)
        # Exit monitor + position/risk sync run every base tick (~5s)
        await self._run_exits(now)
        await self._sync_positions_and_risk(now)
        await self._push_health(now, sess, market_active)

    # ── scanner ────────────────────────────────────────────────────────────────

    async def _run_scan(self, now: datetime) -> None:
        assert self.data is not None
        tier_a: list[dict[str, Any]] = []
        tier_b: list[dict[str, Any]] = []

        # Batch snapshots across the universe.
        syms = STARTER_UNIVERSE
        batch = max(1, self.cfg.snapshot_batch)
        snapshot: dict[str, dict[str, Any]] = {}
        for i in range(0, len(syms), batch):
            chunk = syms[i : i + batch]
            part = await self.data.get_snapshot(chunk)
            snapshot.update(part)
        if snapshot:
            self._last_data_ts = now

        # Tier A wide net
        a_hits: list[tuple[str, dict[str, Any]]] = []
        for sym, snap in snapshot.items():
            price = snap["price"]
            change = snap["change_pct"]
            if price is None:
                continue
            if change >= TIER_A_CHANGE_MIN and TIER_A_PRICE_MIN <= price <= TIER_A_PRICE_MAX:
                a_hits.append((sym, snap))

        a_hits.sort(key=lambda kv: kv[1]["change_pct"], reverse=True)

        for sym, snap in a_hits:
            price = snap["price"]
            change = snap["change_pct"]
            flt = float_for(sym)
            # RVOL only for Tier-A passers (limits API calls)
            rvol = await self.data.get_rvol(sym, current_volume=snap.get("volume"))
            p1 = TIER_B_PRICE_MIN <= price <= TIER_B_PRICE_MAX
            p2 = flt is not None and flt <= TIER_B_FLOAT_MAX
            p3 = rvol is not None and rvol >= TIER_B_RVOL_MIN
            p4 = change >= TIER_B_CHANGE_MIN
            p5 = False  # catalyst not verified in demo
            pillar_flags = {
                "P1_price": p1,
                "P2_float": p2,
                "P3_rvol": p3,
                "P4_roc": p4,
                "P5_catalyst": p5,
            }
            entry = self.state.make_watchlist_entry(
                symbol=sym,
                tier="A",
                price=price,
                rvol=rvol,
                float_shares=flt,
                catalyst="UNVERIFIED (demo: no news feed)",
                pillar_flags=pillar_flags,
                change_pct=change,
            )
            tier_a.append(entry)

            # Tier B (Five Pillars minus catalyst, which is bypassed for the demo)
            if p1 and p2 and p3 and p4:
                b_entry = dict(entry)
                b_entry["tier"] = "B"
                tier_b.append(b_entry)

        self._last_scan_tier_a = tier_a
        self._last_scan_tier_b = tier_b
        await self.state.update_watchlists(tier_a, tier_b)
        log.info("demo_engine.scan tier_a=%d tier_b=%d", len(tier_a), len(tier_b))

    # ── strategy ───────────────────────────────────────────────────────────────

    async def _run_strategy(self, now: datetime, sess: Session) -> None:
        assert self.data is not None
        within_entry_window = self._within_entry_window(now)
        for entry in list(self._last_scan_tier_b):
            sym = entry["symbol"]
            if sym in self.positions:
                continue
            bars = await self.data.get_bars(sym, timeframe="1Min", limit=50)
            if len(bars) < 6:
                continue
            try:
                quote = await self.data.get_quote(sym)
                spread = (quote.ask - quote.bid)
            except Exception:  # noqa: BLE001
                continue
            gate = _evaluate_entry_gate(bars, spread, self.cfg.e6_enabled)
            if not gate.passes:
                continue

            conviction = _conviction(gate, Decimal(entry.get("rvol", "0") or "0"))
            detail = {
                "gates": gate.flags,
                "entry": _s(gate.entry_price or Decimal("0")),
                "stop": _s(gate.stop_price or Decimal("0")),
                "target": _s(gate.target_price or Decimal("0")),
                "spread": _s(spread),
                "e6_bypassed": not self.cfg.e6_enabled,
                "market_state": self.effective_market_state,
            }

            # Risk gate (demo, spec §5)
            approved, veto, shares = self._risk_gate(now, gate, within_entry_window)
            if not approved:
                detail["veto"] = veto
                await self.state.add_signal(
                    self.state.make_signal(sym, "veto", "entry_veto", detail, conviction)
                )
                await self.state.add_risk_event(
                    self.state.make_risk_event("VETO", "WARN", f"{sym}: {veto}", detail)
                )
                continue

            detail["shares"] = shares
            await self.state.add_signal(
                self.state.make_signal(sym, "entry", "entry_signal", detail, conviction)
            )

            if self.effective_auto_trade and self.broker is not None and shares > 0:
                await self._submit_entry(sym, shares, quote.ask, gate, now)

    def _risk_gate(
        self, now: datetime, gate: _GateResult, within_window: bool
    ) -> tuple[bool, str | None, int]:
        """Demo pre-trade gate (spec §5). Returns (approved, veto_reason, shares)."""
        if self._halted_getter() or self.risk.halted:
            return False, "session_halted", 0
        if self._paused_getter():
            return False, "paused", 0
        if not within_window:
            return False, "outside_entry_window(07:00-%s ET)" % self.cfg.hard_stop_time, 0
        if self.risk.consecutive_losses >= 3:
            self._halt("three_consecutive_losses")
            return False, "three_strikes", 0
        if self.risk.realized_pnl <= -self.effective_max_daily_loss:
            self._halt("max_daily_loss")
            return False, "max_daily_loss", 0

        entry = gate.entry_price or Decimal("0")
        stop = gate.stop_price or Decimal("0")
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            return False, "invalid_stop", 0
        shares = int(math.floor(self.cfg.per_trade_risk / risk_per_share))
        # Cushion rule (spec §5): while day P&L <= 0, cap size to 25% of normal.
        if self.risk.realized_pnl <= 0:
            shares = int(shares * 0.25)
        shares = min(shares, self.cfg.max_position_size)
        if shares <= 0:
            return False, "sizing_zero", 0
        return True, None, shares

    async def _submit_entry(
        self, sym: str, shares: int, ask: Decimal, gate: _GateResult, now: datetime
    ) -> None:
        assert self.broker is not None
        limit_price = (ask + BUY_OFFSET).quantize(Decimal("0.01"))
        req = OrderRequest(
            client_order_id=f"demo-{sym}-{int(now.timestamp())}",
            symbol=sym,
            side=Side.BUY,
            qty=shares,
            limit_price=limit_price,
        )
        ack = await self.broker.submit_marketable_limit(req)
        detail = {"limit_price": _s(limit_price), "shares": shares, "ack": ack.status}
        if ack.accepted:
            self.positions[sym] = DemoPosition(
                symbol=sym,
                shares=shares,
                entry_price=gate.entry_price or limit_price,
                stop_price=gate.stop_price or (limit_price - Decimal("0.20")),
                entry_time=now,
            )
            self.risk.trades_today += 1
            await self.state.add_risk_event(
                self.state.make_risk_event("ORDER", "INFO", f"{sym}: BUY {shares} @ {limit_price}", detail)
            )
        else:
            await self.state.add_risk_event(
                self.state.make_risk_event("ORDER_REJECT", "WARN", f"{sym}: {ack.message}", detail)
            )

    # ── exits ──────────────────────────────────────────────────────────────────

    async def _run_exits(self, now: datetime) -> None:
        if not self.positions or self.data is None or self.broker is None:
            return
        for sym, pos in list(self.positions.items()):
            try:
                quote = await self.data.get_quote(sym)
                price = quote.bid  # sell at bid (U7)
            except Exception:  # noqa: BLE001
                continue
            unrealized_ps = price - pos.entry_price
            elapsed = (now - pos.entry_time).total_seconds()
            reason: str | None = None

            if price <= pos.stop_price:
                reason = "P1_hard_stop"
            elif elapsed >= BAILOUT_SECONDS and unrealized_ps < BAILOUT_MOVE and not pos.scaled:
                reason = "P2_time_stop"
            elif not pos.scaled and pos.entry_price > 0 and (
                unrealized_ps / pos.entry_price
            ) >= SCALE_PROFIT_PCT:
                # P5: scale half + move stop to breakeven
                await self._scale_out(sym, pos, price, now)
                continue

            if reason is not None:
                await self._exit_full(sym, pos, price, reason, now)

    async def _scale_out(self, sym: str, pos: DemoPosition, price: Decimal, now: datetime) -> None:
        assert self.broker is not None
        half = max(1, pos.shares // 2)
        ack = await self.broker.partial_sell(
            sym, half, price.quantize(Decimal("0.01")),
            client_order_id=f"demo-scale-{sym}-{int(now.timestamp())}",
        )
        pos.shares -= half
        pos.scaled = True
        realized = (price - pos.entry_price) * Decimal(half)
        self._record_journal(pos, price, half, realized, "P5_scale_half", now)
        pos.stop_price = pos.entry_price  # move to breakeven (after journal records the entry stop)
        self.risk.record_close(realized)
        await self.state.add_signal(
            self.state.make_signal(
                sym, "exit", "scale_out",
                {"reason": "P5_scale_half", "shares": half, "pnl": _s(realized), "ack": ack.status},
            )
        )

    async def _exit_full(
        self, sym: str, pos: DemoPosition, price: Decimal, reason: str, now: datetime
    ) -> None:
        assert self.broker is not None
        ack = await self.broker.flatten_symbol(sym)
        realized = (price - pos.entry_price) * Decimal(pos.shares)
        self._record_journal(pos, price, pos.shares, realized, reason, now)
        self.risk.record_close(realized)
        del self.positions[sym]
        severity = "INFO" if realized >= 0 else "WARN"
        detail = {"reason": reason, "pnl": _s(realized), "shares": pos.shares, "ack": ack.status}
        await self.state.add_signal(
            self.state.make_signal(sym, "exit", reason, detail)
        )
        await self.state.add_risk_event(
            self.state.make_risk_event("EXIT", severity, f"{sym}: {reason} pnl={_s(realized)}", detail)
        )
        if self.risk.consecutive_losses >= 3:
            self._halt("three_consecutive_losses")
        if self.risk.realized_pnl <= -self.effective_max_daily_loss:
            self._halt("max_daily_loss")

    # ── position / risk sync ────────────────────────────────────────────────────

    async def _sync_positions_and_risk(self, now: datetime) -> None:
        positions: list[dict[str, Any]] = []
        unrealized_total = Decimal("0")
        if self.broker is not None:
            broker_positions = await self.broker.get_positions_detailed()
            for bp in broker_positions:
                positions.append(
                    self.state.make_position(
                        bp["symbol"], bp["qty"], bp["avg_entry_price"], bp["current_price"]
                    )
                )
                unrealized_total += bp["unrealized_pl"]

        day_pnl = self.risk.realized_pnl + unrealized_total
        risk = {
            "day_pnl": _s(day_pnl),
            "peak_pnl": _s(max(self.risk.peak_pnl, day_pnl)),
            "max_daily_loss": _s(self.effective_max_daily_loss),
            "give_back_warn": "0.25",
            "give_back_hard": "0.50",
            "consecutive_losses": self.risk.consecutive_losses,
            "is_halted": self.risk.halted or self._halted_getter(),
            "halt_reason": self.risk.halt_reason,
            "is_paused": self._paused_getter(),
            "trades_today": self.risk.trades_today,
            "wins_today": self.risk.wins_today,
            "losses_today": self.risk.losses_today,
        }
        await self.state.update_positions_and_risk(positions, risk)

    async def _push_health(self, now: datetime, sess: Session, market_active: bool) -> None:
        stale_s = (
            (now - self._last_data_ts).total_seconds() if self._last_data_ts else None
        )
        feeds = [
            {
                "feed_name": f"alpaca_data ({self.cfg.alpaca_data_feed.upper()})",
                "last_tick_ts": self._last_data_ts.isoformat() if self._last_data_ts else None,
                "is_stale": stale_s is None or stale_s > 120,
                "stale_seconds": round(stale_s, 1) if stale_s is not None else None,
            },
            {
                "feed_name": "alpaca_broker (paper)",
                "last_tick_ts": now.isoformat() if self._broker_connected else None,
                "is_stale": not self._broker_connected,
                "stale_seconds": 0.0 if self._broker_connected else None,
            },
        ]
        ws_clients = 0
        if self._connection_count is not None:
            try:
                ws_clients = int(self._connection_count())
            except Exception:  # noqa: BLE001
                ws_clients = 0
        health = {
            "feeds": feeds,
            "clock_drift_ms": 0.0,
            "avg_order_ack_ms": None,
            "ws_client_count": ws_clients,
            "all_healthy": self._broker_connected,
            "checked_at": now.isoformat(),
            "session": str(sess),
            "market_active": market_active,
            "et_time": et_time(now).strftime("%H:%M:%S"),
        }
        await self.state.update_health(health)

    # ── replay (market closed) ───────────────────────────────────────────────────

    async def _replay_step(self) -> None:
        """Generate deterministic synthetic activity so the dashboard looks alive
        outside market hours. Clearly labelled REPLAY in the UI."""
        self._replay_tick += 1
        t = self._replay_tick
        n = len(STARTER_UNIVERSE)
        tier_a: list[dict[str, Any]] = []
        tier_b: list[dict[str, Any]] = []
        for i in range(12):
            sym = STARTER_UNIVERSE[(t + i * 7) % n]
            seed = (hash((sym, t // 3)) % 1000) / 1000.0
            change = Decimal(str(round(4 + seed * 30, 2)))
            price = Decimal(str(round(1.5 + seed * 15, 2)))
            flt = float_for(sym)
            rvol = Decimal(str(round(2 + seed * 12, 1)))
            p1 = TIER_B_PRICE_MIN <= price <= TIER_B_PRICE_MAX
            p2 = flt is not None and flt <= TIER_B_FLOAT_MAX
            p3 = rvol >= TIER_B_RVOL_MIN
            p4 = change >= TIER_B_CHANGE_MIN
            flags = {"P1_price": p1, "P2_float": p2, "P3_rvol": p3, "P4_roc": p4, "P5_catalyst": False}
            entry = self.state.make_watchlist_entry(
                sym, "A", price, rvol, flt, "REPLAY (synthetic)", flags, change_pct=change
            )
            tier_a.append(entry)
            if p1 and p2 and p3 and p4:
                b = dict(entry)
                b["tier"] = "B"
                tier_b.append(b)
        await self.state.update_watchlists(tier_a, tier_b)

        # Occasionally emit a synthetic signal so the feed animates.
        if t % 3 == 0 and tier_b:
            pick = tier_b[t % len(tier_b)]
            sym = pick["symbol"]
            detail = {
                "gates": {"E1": True, "E2": True, "E3": True, "E4": True, "E5": True, "E6_bypassed": True, "E7": True},
                "mode": "REPLAY",
                "note": "synthetic demo signal (market closed)",
            }
            await self.state.add_signal(
                self.state.make_signal(sym, "entry", "entry_signal", detail, 0.6 + (t % 4) * 0.1)
            )

    # ── manual test-signal injection (demo checklist) ────────────────────────────

    async def inject_test_signal(self, symbol: str = "TEST") -> dict[str, Any]:
        detail = {
            "gates": {"E1": True, "E2": True, "E3": True, "E4": True, "E5": True, "E6_bypassed": True, "E7": True},
            "mode": "MANUAL_TEST",
            "note": "manually injected test signal",
        }
        sig = self.state.make_signal(symbol, "entry", "entry_signal", detail, 0.95)
        await self.state.add_signal(sig)
        await self.state.add_risk_event(
            self.state.make_risk_event("TEST", "INFO", f"Manual test signal: {symbol}", detail)
        )
        return sig

    # ── helpers ──────────────────────────────────────────────────────────────────

    def _within_entry_window(self, now: datetime) -> bool:
        t = et_time(now)
        try:
            hh, mm = (int(x) for x in self.cfg.hard_stop_time.split(":"))
        except ValueError:
            hh, mm = 11, 0
        from datetime import time as _time

        start = _time(7, 0)
        end = _time(hh, mm)
        return start <= t <= end

    def _halt(self, reason: str) -> None:
        if not self.risk.halted:
            self.risk.halted = True
            self.risk.halt_reason = reason
            log.warning("demo_engine.halt reason=%s", reason)

    async def _emit_info(self, message: str) -> None:
        await self.state.add_risk_event(
            self.state.make_risk_event("INFO", "INFO", message, {})
        )

    def _record_journal(
        self,
        pos: DemoPosition,
        exit_price: Decimal,
        shares: int,
        realized: Decimal,
        reason: str,
        now: datetime,
    ) -> None:
        """Append one completed (partial or full) trade to the session journal."""
        risk_ps = pos.entry_price - pos.stop_price
        per_share = (exit_price - pos.entry_price)
        r_multiple = float(per_share / risk_ps) if risk_ps > 0 else None
        self.closed_trades.append(
            {
                "symbol": pos.symbol,
                "side": "long",
                "entry_price": _s(pos.entry_price),
                "exit_price": _s(exit_price),
                "shares": int(shares),
                "pnl": _s(realized),
                "r_multiple": round(r_multiple, 2) if r_multiple is not None else None,
                "exit_reason": reason,
                "entry_ts": pos.entry_time.isoformat(),
                "exit_ts": now.isoformat(),
            }
        )

    def journal_today(self) -> list[dict[str, Any]]:
        """Completed trades this session, newest first (GET /api/journal/today)."""
        return list(reversed(self.closed_trades))

    def session_summary(self) -> dict[str, Any]:
        """Win rate / averages / profit factor for the session (GET /api/journal/session-summary)."""
        trades = self.closed_trades
        wins = [t for t in trades if Decimal(t["pnl"]) > 0]
        losses = [t for t in trades if Decimal(t["pnl"]) < 0]
        total = len(wins) + len(losses)
        win_sum = sum((Decimal(t["pnl"]) for t in wins), Decimal("0"))
        loss_sum = sum((Decimal(t["pnl"]) for t in losses), Decimal("0"))
        avg_win = (win_sum / len(wins)) if wins else Decimal("0")
        avg_loss = (loss_sum / len(losses)) if losses else Decimal("0")
        profit_factor = float(win_sum / abs(loss_sum)) if loss_sum != 0 else None
        best = max((Decimal(t["pnl"]) for t in trades), default=Decimal("0"))
        worst = min((Decimal(t["pnl"]) for t in trades), default=Decimal("0"))
        return {
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / total, 4) if total else None,
            "avg_winner": _s(avg_win),
            "avg_loser": _s(avg_loss),
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "best_trade": _s(best),
            "worst_trade": _s(worst),
            "realized_pnl": _s(self.risk.realized_pnl),
            "consecutive_losses": self.risk.consecutive_losses,
            "rules_violated": 0,
        }

    # ── operator console: manual controls (spec §11 / dashboard) ─────────────────
    # Every action below is operator-initiated from the dashboard. Entry actions
    # (manual orders) still pass _manual_guardrails (U4/U5/U7 hard gate). Exit/flatten
    # actions reduce risk and are always permitted. All write an audit risk_event.

    def _manual_guardrails(self, now: datetime) -> str | None:
        """Hard-guardrail gate for operator-initiated BUY orders (U4/U5).

        Returns a veto reason string, or None if the order may proceed. Mirrors the
        autonomous _risk_gate's NON-NEGOTIABLE checks (halt, pause, 3-strikes,
        daily-loss) but intentionally does NOT enforce the soft entry-time window —
        a manual override is a deliberate human decision (the window is a §5 timing
        rule, not a U1–U15 guardrail). Limit-only (U7) is enforced by construction.
        """
        if self._halted_getter() or self.risk.halted:
            return "session_halted"
        if self._paused_getter():
            return "paused"
        if self.risk.consecutive_losses >= 3:
            self._halt("three_consecutive_losses")
            return "three_strikes"
        if self.risk.realized_pnl <= -self.effective_max_daily_loss:
            self._halt("max_daily_loss")
            return "max_daily_loss"
        return None

    async def trigger_scan(self) -> dict[str, Any]:
        """Run one scan immediately (POST /api/scanner/trigger)."""
        if self.data is None:
            # No live data → surface current replay/last scan instead of erroring.
            return {
                "ok": False,
                "message": "no live market data (closed market or no credentials)",
                "tier_a": len(self._last_scan_tier_a),
                "tier_b": len(self._last_scan_tier_b),
            }
        await self._run_scan(now_utc())
        await self._emit_info("Manual scan triggered from dashboard")
        return {
            "ok": True,
            "tier_a": len(self._last_scan_tier_a),
            "tier_b": len(self._last_scan_tier_b),
        }

    async def get_bars_payload(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        """Last ``limit`` 1-min bars for a symbol as JSON (chart fallback feed)."""
        if self.data is None:
            return []
        sym = symbol.upper().strip()
        try:
            bars = await self.data.get_bars(sym, timeframe="1Min", limit=limit)
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        for b in bars:
            out.append(
                {
                    "time": int(b.ts.timestamp()),
                    "open": _s(b.open),
                    "high": _s(b.high),
                    "low": _s(b.low),
                    "close": _s(b.close),
                    "volume": int(b.volume),
                }
            )
        return out

    async def close_position(self, symbol: str) -> dict[str, Any]:
        """Operator full close of a position at the bid (limit-style exit)."""
        sym = symbol.upper().strip()
        if self.broker is None:
            return {"ok": False, "message": "broker not connected"}
        pos = self.positions.get(sym)
        now = now_utc()
        # Mark price for PnL accounting (fall back to entry on quote failure).
        price = pos.entry_price if pos else Decimal("0")
        if self.data is not None:
            try:
                price = (await self.data.get_quote(sym)).bid
            except Exception:  # noqa: BLE001
                pass
        ack = await self.broker.flatten_symbol(sym)
        if pos is not None:
            realized = (price - pos.entry_price) * Decimal(pos.shares)
            self._record_journal(pos, price, pos.shares, realized, "manual_close", now)
            self.risk.record_close(realized)
            del self.positions[sym]
        else:
            realized = Decimal("0")
        detail = {"reason": "manual_close", "pnl": _s(realized), "ack": ack.status}
        await self.state.add_signal(self.state.make_signal(sym, "exit", "manual_close", detail))
        await self.state.add_risk_event(
            self.state.make_risk_event("MANUAL_EXIT", "INFO", f"{sym}: operator close pnl={_s(realized)}", detail)
        )
        await self._sync_positions_and_risk(now)
        return {"ok": ack.accepted, "message": ack.status, "pnl": _s(realized)}

    async def scale_out_position(self, symbol: str) -> dict[str, Any]:
        """Operator scale-out: sell half the position at the bid, stop → breakeven."""
        sym = symbol.upper().strip()
        if self.broker is None:
            return {"ok": False, "message": "broker not connected"}
        pos = self.positions.get(sym)
        if pos is None or pos.shares <= 1:
            return {"ok": False, "message": "no position large enough to scale"}
        now = now_utc()
        price = pos.entry_price
        if self.data is not None:
            try:
                price = (await self.data.get_quote(sym)).bid
            except Exception:  # noqa: BLE001
                pass
        await self._scale_out(sym, pos, price, now)
        await self._sync_positions_and_risk(now)
        return {"ok": True, "message": "scaled 50%", "remaining_shares": pos.shares}

    async def move_stop(self, symbol: str, stop_price: Decimal) -> dict[str, Any]:
        """Operator move of the internal mental stop (U13 — no resting broker stop)."""
        sym = symbol.upper().strip()
        pos = self.positions.get(sym)
        if pos is None:
            return {"ok": False, "message": "no open position"}
        old = pos.stop_price
        pos.stop_price = stop_price.quantize(Decimal("0.01"))
        detail = {"old_stop": _s(old), "new_stop": _s(pos.stop_price)}
        await self.state.add_risk_event(
            self.state.make_risk_event("MANUAL_STOP", "INFO", f"{sym}: mental stop → {_s(pos.stop_price)}", detail)
        )
        return {"ok": True, "stop_price": _s(pos.stop_price)}

    async def manual_order(
        self, symbol: str, side: str, qty: int, limit_price: Decimal
    ) -> dict[str, Any]:
        """Quick manual paper order. BUY routes through the U4/U5/U7 hard gate."""
        sym = symbol.upper().strip()
        side_u = side.upper().strip()
        if self.broker is None:
            return {"ok": False, "approved": False, "veto": "broker_not_connected"}
        if qty <= 0:
            return {"ok": False, "approved": False, "veto": "invalid_qty"}
        now = now_utc()
        is_buy = side_u == "BUY"
        if is_buy:
            veto = self._manual_guardrails(now)
            if veto is not None:
                await self.state.add_risk_event(
                    self.state.make_risk_event("VETO", "WARN", f"{sym}: manual order vetoed ({veto})", {"side": side_u})
                )
                return {"ok": False, "approved": False, "veto": veto}
            # Liquidity clamp (U9): never exceed the per-order share cap.
            qty = min(qty, self.cfg.max_position_size)
        limit = limit_price.quantize(Decimal("0.01"))
        req = OrderRequest(
            client_order_id=f"manual-{sym}-{int(now.timestamp())}",
            symbol=sym,
            side=Side.BUY if is_buy else Side.SELL,
            qty=qty,
            limit_price=limit,
        )
        ack = await self.broker.submit_marketable_limit(req)
        detail = {"side": side_u, "qty": qty, "limit_price": _s(limit), "ack": ack.status, "source": "manual"}
        if ack.accepted and is_buy:
            # Track so the exit monitor / dashboard sees the position.
            self.positions[sym] = DemoPosition(
                symbol=sym,
                shares=qty,
                entry_price=limit,
                stop_price=(limit - Decimal("0.20")),
                entry_time=now,
            )
            self.risk.trades_today += 1
        await self.state.add_signal(
            self.state.make_signal(sym, "entry" if is_buy else "exit", "manual_order", detail)
        )
        await self.state.add_risk_event(
            self.state.make_risk_event("MANUAL_ORDER", "INFO" if ack.accepted else "WARN",
                                       f"{sym}: {side_u} {qty} @ {_s(limit)} ({ack.status})", detail)
        )
        await self._sync_positions_and_risk(now)
        return {"ok": ack.accepted, "approved": True, "status": ack.status, "qty": qty, "limit_price": _s(limit)}

    async def manual_trade(
        self, symbol: str, entry: Decimal, stop: Decimal, shares: int
    ) -> dict[str, Any]:
        """Execute an AI-suggested trade. Sizing is RESIZED by the risk gate.

        Reuses the autonomous sizing logic: per-trade-risk / risk-per-share, cushion
        cap while day P&L <= 0, and the liquidity cap. The caller's ``shares`` is an
        upper bound only — the gate may shrink it. spec §5/§6.
        """
        sym = symbol.upper().strip()
        if self.broker is None:
            return {"ok": False, "approved": False, "veto": "broker_not_connected"}
        now = now_utc()
        veto = self._manual_guardrails(now)
        if veto is not None:
            await self.state.add_risk_event(
                self.state.make_risk_event("VETO", "WARN", f"{sym}: AI trade vetoed ({veto})", {})
            )
            return {"ok": False, "approved": False, "veto": veto}
        entry_d = entry.quantize(Decimal("0.01"))
        stop_d = stop.quantize(Decimal("0.01"))
        risk_per_share = entry_d - stop_d
        if risk_per_share <= 0:
            return {"ok": False, "approved": False, "veto": "invalid_stop"}
        sized = int(math.floor(self.cfg.per_trade_risk / risk_per_share))
        if self.risk.realized_pnl <= 0:  # cushion rule (§5): ¼ size while not green
            sized = int(sized * 0.25)
        sized = min(sized, max(0, int(shares)), self.cfg.max_position_size)
        if sized <= 0:
            return {"ok": False, "approved": False, "veto": "sizing_zero"}
        result = await self.manual_order(sym, "BUY", sized, entry_d + BUY_OFFSET)
        if result.get("ok") and sym in self.positions:
            self.positions[sym].stop_price = stop_d  # honour the AI's stop level
        result["sized_shares"] = sized
        result["requested_shares"] = int(shares)
        return result

    async def flatten_all(self) -> dict[str, Any]:
        """Operator flatten: cancel orders + close all positions (kill-switch path)."""
        if self.broker is None:
            self.positions.clear()
            return {"ok": False, "positions_closed": 0, "orders_cancelled": 0, "message": "broker not connected"}
        closed = len(self.positions)
        acks = await self.broker.cancel_all_flatten()
        self.positions.clear()
        await self.state.add_risk_event(
            self.state.make_risk_event("FLATTEN", "CRITICAL", f"Operator FLATTEN ALL ({closed} positions)", {"acks": len(acks)})
        )
        await self._sync_positions_and_risk(now_utc())
        return {"ok": True, "positions_closed": closed, "orders_cancelled": len(acks)}

    def halt_day(self, reason: str = "manual_halt_day") -> dict[str, Any]:
        """Operator halt for the rest of the session (same effect as 3-strikes)."""
        self._halt(reason)
        return {"ok": True, "halted": True, "reason": reason}

    async def set_override(self, key: str, value: Any) -> dict[str, Any]:
        """Apply an audited session-config override (U11 dashboard exception).

        Supported keys: AUTO_TRADE, MARKET_STATE, MAX_DAILY_LOSS, SCAN_INTERVAL.
        Every change writes a risk_event audit row. See spec Appendix A.
        """
        key = key.upper().strip()
        before: Any
        if key == "AUTO_TRADE":
            before = self.effective_auto_trade
            self.session_overrides["AUTO_TRADE"] = bool(value)
        elif key == "MARKET_STATE":
            v = str(value).upper().strip()
            if v not in {"HOT", "COLD", "REHAB"}:
                return {"ok": False, "message": "MARKET_STATE must be HOT|COLD|REHAB"}
            before = self.effective_market_state
            self.session_overrides["MARKET_STATE"] = v
        elif key == "MAX_DAILY_LOSS":
            before = _s(self.effective_max_daily_loss)
            self.session_overrides["MAX_DAILY_LOSS"] = Decimal(str(value))
        elif key == "SCAN_INTERVAL":
            before = self.effective_scan_interval_s
            self.session_overrides["SCAN_INTERVAL"] = int(value)
        else:
            return {"ok": False, "message": f"unsupported config key: {key}"}
        after = self.session_overrides[key]
        after_str = _s(after) if isinstance(after, Decimal) else after
        detail = {"key": key, "before": before, "after": after_str, "spec_ref": "U11_dashboard_exception"}
        await self.state.add_risk_event(
            self.state.make_risk_event("CONFIG_OVERRIDE", "WARN",
                                       f"Session override: {key} {before} → {after_str}", detail)
        )
        return {"ok": True, "key": key, "value": after_str}

    def effective_config(self) -> dict[str, Any]:
        """Current effective values of the four overridable keys (for GET /api/config)."""
        return {
            "AUTO_TRADE": self.effective_auto_trade,
            "MARKET_STATE": self.effective_market_state,
            "MAX_DAILY_LOSS": _s(self.effective_max_daily_loss),
            "SCAN_INTERVAL": self.effective_scan_interval_s,
            "overridden": sorted(self.session_overrides.keys()),
        }


# ── pure gate helpers (spec §2) ─────────────────────────────────────────────────


def _evaluate_entry_gate(bars: list[Any], spread: Decimal, e6_enabled: bool) -> _GateResult:
    """Simplified E1–E7 AND-gate (spec §2). E6 bypassed unless e6_enabled."""
    flags: dict[str, bool] = {}
    if len(bars) < 6:
        return _GateResult(False, {"E0_insufficient_bars": False})

    breakout = bars[-1]
    pullback = bars[-3:-1]          # 2 bars before the breakout
    surge = bars[-8:-3] if len(bars) >= 8 else bars[:-3]

    # E1 — universe (passed Tier B by construction here)
    e1 = True
    # E2 — pullback: the two bars before breakout are red
    e2 = len(pullback) == 2 and all(b.close < b.open for b in pullback)
    # E3 — breakout makes a new high vs the prior bar
    e3 = breakout.high > bars[-2].high
    # E4 — MACD positive / crossing up
    closes = [b.close for b in bars]
    e4 = macd_positive(macd(closes)[-1])
    # E5 — retrace held within RETRACE_MAX of the surge
    surge_high = max((b.high for b in surge + list(pullback)), default=breakout.high)
    surge_start = surge[0].low if surge else bars[0].low
    pullback_low = min((b.low for b in pullback), default=breakout.low)
    surge_range = surge_high - surge_start
    if surge_range > 0:
        e5 = pullback_low >= surge_high - RETRACE_MAX * surge_range
    else:
        e5 = False
    # E6 — L2 support: BYPASSED for the demo (no Alpaca depth)
    e6 = True if not e6_enabled else False
    # E7 — healthy spread band
    e7 = SPREAD_MIN <= spread <= SPREAD_MAX

    flags = {
        "E1_universe": e1,
        "E2_pullback": e2,
        "E3_breakout": e3,
        "E4_macd": e4,
        "E5_retrace": e5,
        "E6_l2_bypassed": True if not e6_enabled else e6,
        "E7_spread": e7,
    }
    passes = e1 and e2 and e3 and e4 and e5 and e6 and e7
    entry_price = breakout.close
    stop_price = pullback_low
    risk = entry_price - stop_price
    target_price = entry_price + (risk * Decimal("2")) if risk > 0 else entry_price
    return _GateResult(
        passes=passes,
        flags=flags,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
    )


def _conviction(gate: _GateResult, rvol: Decimal) -> float:
    """Rough conviction score [0.25, 1.0] for the demo feed colouring."""
    base = 0.5
    if rvol >= Decimal("10"):
        base += 0.25
    elif rvol >= Decimal("5"):
        base += 0.15
    passed = sum(1 for v in gate.flags.values() if v)
    base += min(0.25, passed * 0.03)
    return round(min(1.0, max(0.25, base)), 2)
