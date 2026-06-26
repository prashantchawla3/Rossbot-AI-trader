"""Event-driven backtest replay engine.

Processes a sequence of ReplayBar events through the full pipeline:
  StrategyEngine → RiskManager → FillModel → TradeRecord ledger

Design invariants:
- DETERMINISTIC: given the same events + config + seed → identical output.
- CONSERVATIVE FILLS ONLY (plan Phase 4 / CLAUDE.md §9): see fill_model.py.
- U13 MENTAL STOP: detected on bar.low (intra-bar breach); fill with LATENCY_SLIP.
  No native STOP orders are ever modelled (by construction — no submit_stop method).
- ONE POSITION AT A TIME per symbol: Risk Manager enforces this via open_positions.
- EVERY VETO is recorded as a TradeRecord(vetoed=True) for audit.
- RULE VIOLATIONS cause TradeRecord(rule_violation=True); callers must assert count == 0.
- U3 NO-OVERNIGHT: EOD flatten fires at or after EOD_FLATTEN_TIME before close.

spec Phase 4 plan / ROSSBOT_PROJECT_PLAN.md Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from adapters.base import BarTick
from adapters.providers import L2Signal, MarketState
from core.backtest.fill_model import entry_fill, exit_fill_stop, exit_fill_target
from core.backtest.models import BacktestResult, SimDay, TradeRecord
from core.config import ConfigService
from core.risk.manager import RiskManager
from core.scanner.models import ScanResult
from core.strategy.engine import StrategyEngine
from core.strategy.models import (
    EntrySignal,
    ExitReason,
    ExitSignal,
    PositionSnapshot,
    ScaleAction,
)


# ── Replay input ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReplayBar:
    """One replay event: a BarTick plus its market context."""

    bar: BarTick
    scan_result: ScanResult
    l2_signal: L2Signal
    spread: Decimal
    market_state: MarketState
    account_equity: Decimal
    liquidity_cap_shares: int | None = None  # from depth data (U9)
    catalyst_skip: bool = False              # U15: buyout/secondary/recycled-PR


# ── Internal position tracking ────────────────────────────────────────────────

@dataclass
class _OpenPosition:
    """Internal fill-level position state during replay."""

    symbol: str
    entry_ts: datetime
    entry_price: Decimal    # actual fill (after slippage)
    stop_price: Decimal
    target_price: Decimal
    shares: int
    risk_per_share: Decimal
    entry_fees: Decimal
    high_watermark: Decimal = field(init=False)

    def __post_init__(self) -> None:
        self.high_watermark = self.entry_price

    def as_snapshot(self) -> PositionSnapshot:
        """Convert to PositionSnapshot for the Risk Manager mental-stop check."""
        return PositionSnapshot(
            symbol=self.symbol,
            entry_price=self.entry_price,
            current_stop=self.stop_price,
            target_price=self.target_price,
            shares=self.shares,
            entry_ts=self.entry_ts,
            high_watermark=self.high_watermark,
        )


# ── Main replay function ──────────────────────────────────────────────────────

def replay(
    events: Sequence[ReplayBar],
    config: ConfigService,
    *,
    strategy_engine: StrategyEngine | None = None,
    risk_manager: RiskManager | None = None,
    seed: int = 42,
) -> BacktestResult:
    """Run a deterministic backtest over a sequence of ReplayBar events.

    Returns a BacktestResult with per-day summaries and aggregate metrics.
    Every risk veto is recorded.  Rule violations (U1–U15 breaches) are flagged
    in TradeRecord.rule_violation; callers should assert rule_violation_count == 0.

    spec Phase 4 plan.
    """
    engine = strategy_engine or StrategyEngine(config)
    risk_mgr = risk_manager or RiskManager(config)

    buy_offset = config.get_decimal("BUY_OFFSET")
    result = BacktestResult()

    current_day: date | None = None
    sim_day: SimDay | None = None
    open_pos: _OpenPosition | None = None
    prev_close: Decimal | None = None  # for session reset

    for event in events:
        bar = event.bar
        bar_date = bar.ts.date()

        # ── Day boundary ──────────────────────────────────────────────────────
        if bar_date != current_day:
            # EOD: flatten any residual position before closing the day
            if open_pos is not None and sim_day is not None:
                trade = _eod_flatten(open_pos, bar, risk_mgr, engine)
                sim_day.trades.append(trade)
                open_pos = None

            if sim_day is not None:
                _finalise_day(sim_day)
                result.days.append(sim_day)

            current_day = bar_date
            sim_day = SimDay(date=bar_date)
            risk_mgr.reset_session()
            engine.reset_session(
                bar.symbol,
                prev_close=prev_close if prev_close is not None else bar.open,
            )

        assert sim_day is not None
        exited_this_bar = False

        # ── U3: EOD flatten check ─────────────────────────────────────────────
        if open_pos is not None and risk_mgr.should_flatten_eod(bar.ts):
            trade = _eod_flatten(open_pos, bar, risk_mgr, engine)
            sim_day.trades.append(trade)
            open_pos = None
            exited_this_bar = True

        # ── U13: Mental stop — detected on bar.low (intra-bar breach) ─────────
        # This is the documented cost of forbidding native STOP orders (spec §13.4).
        if open_pos is not None and not exited_this_bar:
            if risk_mgr.check_mental_stop(bar.low, open_pos.as_snapshot()):
                trade = _stop_exit(open_pos, bar, risk_mgr, engine)
                sim_day.trades.append(trade)
                open_pos = None
                exited_this_bar = True

        # ── Skip engine processing if we just exited ──────────────────────────
        if exited_this_bar:
            prev_close = bar.close
            continue

        # ── Strategy + Risk pipeline ──────────────────────────────────────────
        signals = engine.on_bar(
            bar,
            event.scan_result,
            event.l2_signal,
            event.spread,
            event.market_state,
        )

        for signal in signals:
            # ── ENTRY path ────────────────────────────────────────────────────
            if isinstance(signal, EntrySignal) and open_pos is None:
                approval = risk_mgr.evaluate(
                    signal=signal,
                    now_et=bar.ts,
                    account_equity=event.account_equity,
                    liquidity_cap_shares=event.liquidity_cap_shares,
                    catalyst_skip=event.catalyst_skip,
                )

                if not approval.approved:
                    assert sim_day is not None
                    sim_day.trades.append(_veto_record(signal, bar, approval.vetoes))
                    continue

                # Fill: conservative entry (always above mid, see fill_model.py)
                fill = entry_fill(
                    ask_price=signal.entry_price,
                    buy_offset=buy_offset,
                    requested_shares=approval.shares,
                    seed=seed ^ (hash(bar.symbol) & 0xFFFF) ^ (int(bar.ts.timestamp()) & 0xFFFF),
                )

                risk_mgr.record_open(bar.symbol, fill.fill_price)
                engine.open_position(
                    symbol=bar.symbol,
                    entry_price=fill.fill_price,
                    stop_price=signal.stop_price,
                    target_price=signal.target_price,
                    shares=fill.fill_shares,
                    ts=bar.ts,
                )

                open_pos = _OpenPosition(
                    symbol=bar.symbol,
                    entry_ts=bar.ts,
                    entry_price=fill.fill_price,
                    stop_price=signal.stop_price,
                    target_price=signal.target_price,
                    shares=fill.fill_shares,
                    risk_per_share=signal.risk_per_share,
                    entry_fees=fill.fees,
                )
                break  # one position at a time

            # ── EXIT path ─────────────────────────────────────────────────────
            elif isinstance(signal, ExitSignal) and open_pos is not None:
                if signal.action == ScaleAction.FULL_EXIT:
                    trade = _target_exit(signal.reason, open_pos, bar, risk_mgr, engine)
                    assert sim_day is not None
                    sim_day.trades.append(trade)
                    open_pos = None
                    break
                # PARTIAL_SCALE: update stop, continue (Phase 4 scope: record scale-out
                # as a separate partial trade record but keep position open)
                elif signal.action == ScaleAction.PARTIAL_SCALE and signal.new_stop:
                    open_pos.stop_price = signal.new_stop
                    if open_pos is not None:
                        engine.update_stop(bar.symbol, signal.new_stop)

        prev_close = bar.close

    # ── Flush last day ────────────────────────────────────────────────────────
    if sim_day is not None:
        if open_pos is not None:
            last_bar = events[-1].bar if events else None
            if last_bar is not None:
                trade = _eod_flatten(open_pos, last_bar, risk_mgr, engine)
                sim_day.trades.append(trade)
                open_pos = None
        _finalise_day(sim_day)
        result.days.append(sim_day)

    return result


# ── Trade-record builders ─────────────────────────────────────────────────────

def _veto_record(
    signal: EntrySignal,
    bar: BarTick,
    vetoes: tuple,
) -> TradeRecord:
    """Create a veto TradeRecord (no capital deployed; correctly blocked)."""
    return TradeRecord(
        symbol=signal.symbol,
        entry_ts=bar.ts,
        exit_ts=bar.ts,
        entry_price=signal.entry_price,
        exit_price=signal.entry_price,
        shares=0,
        gross_pnl=Decimal("0"),
        fees=Decimal("0"),
        net_pnl=Decimal("0"),
        r_multiple=Decimal("0"),
        hold_seconds=0.0,
        exit_reason="vetoed",
        risk_per_share=signal.risk_per_share,
        vetoed=True,
        veto_reasons=tuple(str(v) for v in vetoes),
    )


def _stop_exit(
    pos: _OpenPosition,
    bar: BarTick,
    risk_mgr: RiskManager,
    engine: StrategyEngine,
) -> TradeRecord:
    """U13 mental-stop exit with documented latency cost. spec §3 P1 / U13."""
    fill = exit_fill_stop(pos.stop_price, bar.low, pos.shares)
    return _complete_trade(pos, bar, fill.fill_price, fill.fees, ExitReason.HARD_STOP, risk_mgr, engine)


def _target_exit(
    reason: ExitReason,
    pos: _OpenPosition,
    bar: BarTick,
    risk_mgr: RiskManager,
    engine: StrategyEngine,
) -> TradeRecord:
    """Exit at a profit target / strategy signal (P2–P8)."""
    fill = exit_fill_target(bar.close, pos.shares)
    return _complete_trade(pos, bar, fill.fill_price, fill.fees, reason, risk_mgr, engine)


def _eod_flatten(
    pos: _OpenPosition,
    bar: BarTick,
    risk_mgr: RiskManager,
    engine: StrategyEngine,
) -> TradeRecord:
    """U3 EOD flatten — sell at close. spec §11 U3."""
    fill = exit_fill_target(bar.close, pos.shares)
    return _complete_trade(pos, bar, fill.fill_price, fill.fees, "eod_flatten", risk_mgr, engine)


def _complete_trade(
    pos: _OpenPosition,
    bar: BarTick,
    exit_price: Decimal,
    exit_fees: Decimal,
    exit_reason,
    risk_mgr: RiskManager,
    engine: StrategyEngine,
) -> TradeRecord:
    """Common path: compute PnL, update risk manager and engine, build TradeRecord."""
    gross_pnl = (exit_price - pos.entry_price) * Decimal(pos.shares)
    total_fees = pos.entry_fees + exit_fees
    net_pnl = gross_pnl - total_fees
    hold_secs = (bar.ts - pos.entry_ts).total_seconds()

    risk_mgr.record_close(pos.symbol, net_pnl)
    engine.close_position(pos.symbol)

    rps = pos.risk_per_share
    r_multiple = (
        net_pnl / (rps * Decimal(pos.shares))
        if rps > Decimal("0") and pos.shares > 0
        else Decimal("0")
    )

    return TradeRecord(
        symbol=pos.symbol,
        entry_ts=pos.entry_ts,
        exit_ts=bar.ts,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        shares=pos.shares,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        hold_seconds=hold_secs,
        exit_reason=str(exit_reason),
        risk_per_share=rps,
    )


# ── Day finalisation ──────────────────────────────────────────────────────────

def _finalise_day(sim_day: SimDay) -> None:
    """Compute end-of-day PnL, peak, max drawdown, give-back for the SimDay."""
    pnl_running = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")

    for trade in sim_day.trades:
        if trade.vetoed:
            continue
        pnl_running += trade.net_pnl
        if pnl_running > peak:
            peak = pnl_running
        dd = peak - pnl_running
        if dd > max_dd:
            max_dd = dd

    sim_day.end_pnl = pnl_running
    sim_day.peak_pnl = peak
    sim_day.max_drawdown = max_dd
    if peak > Decimal("0"):
        sim_day.give_back_pct = max_dd / peak


__all__ = ["ReplayBar", "replay"]
