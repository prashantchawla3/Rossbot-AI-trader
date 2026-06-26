"""StrategyEngine — wires the entry gate, pattern recogniser, conviction
scorer, and exit engine into a per-symbol stateful processor.

Design rules:
- Outputs signals ONLY.  Nothing routes to a broker here.
- Phase 3 Risk Manager sits between every signal and the execution layer.
- Pure-function helpers do all logic; the engine just maintains state.
- 1-min bars drive signals; 10-sec bars update intraday_high but don't
  trigger entry/exit decisions (10s charts used for micro-pullback detail
  in a later phase).
- Session reset clears bar history and indicator states but NOT the
  pattern / conviction memory (those are stateless functions).

spec §2 entry, §3 exit, §4/§4A patterns, §6 conviction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Union

from adapters.base import BarTick
from adapters.providers import L2Signal, MarketState
from core.config import ConfigService, StopBasis
from core.indicators import EmaState, MacdState, MacdPoint, VwapState
from core.money import Money
from core.scanner.models import ScanResult
from core.strategy.conviction import score_conviction
from core.strategy.entry_gate import evaluate_entry_gate
from core.strategy.exit_engine import evaluate_exit
from core.strategy.models import (
    EntrySignal,
    ExitSignal,
    FailedPatternSignal,
    PositionSnapshot,
    ScaleAction,
)
from core.strategy.patterns import is_failed_pattern, recognize_pattern

_BAR_WINDOW = 50    # sliding window: last N 1-min bars
_10S_WINDOW = 100   # 10-sec sliding window (≈ 16 min)
_TWO = Decimal("2")
_TINY = Decimal("0.01")

Signal = Union[EntrySignal, ExitSignal, FailedPatternSignal]


@dataclass
class SymbolState:
    """Per-symbol running state (bars, indicators, open position)."""

    bars_1m: list[BarTick] = field(default_factory=list)
    bars_10s: list[BarTick] = field(default_factory=list)
    macd_state: MacdState = field(default_factory=MacdState)
    ema9_state: EmaState = field(default_factory=lambda: EmaState(9))
    vwap_state: VwapState = field(default_factory=VwapState)
    position: PositionSnapshot | None = None
    intraday_high: Decimal = field(default_factory=lambda: Decimal("0"))
    prev_close: Decimal | None = None
    gap_pct: Decimal = field(default_factory=lambda: Decimal("0"))
    is_halted_resume: bool = False
    market_rank: int | None = None


class StrategyEngine:
    """Per-symbol state manager + signal dispatcher.

    Usage::

        engine = StrategyEngine(config)
        engine.reset_session("AAPL", prev_close=Decimal("174.50"))
        signals = engine.on_bar(bar, scan_result, l2_signal, spread, market_state)

    After a fill, call ``open_position`` so the exit engine has a target.
    After a close, call ``close_position`` to clear state.
    """

    def __init__(self, config: ConfigService) -> None:
        self._cfg = config
        self._states: dict[str, SymbolState] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # Session lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def reset_session(
        self,
        symbol: str,
        prev_close: Decimal,
        gap_pct: Decimal = Decimal("0"),
    ) -> None:
        """Reset per-session indicator + bar state at market open.

        U3 (no overnight): also clears any lingering position (should not
        happen in production — flatten is enforced before close).
        """
        s = self._states.setdefault(symbol, SymbolState())
        s.bars_1m.clear()
        s.bars_10s.clear()
        s.macd_state = MacdState()
        s.ema9_state = EmaState(9)
        s.vwap_state = VwapState()
        s.position = None  # spec U3: no overnight holds
        s.intraday_high = Decimal("0")
        s.prev_close = prev_close
        s.gap_pct = gap_pct
        s.is_halted_resume = False
        s.market_rank = None

    # ──────────────────────────────────────────────────────────────────────────
    # Position lifecycle (called by the execution / risk layer after fills)
    # ──────────────────────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_price: Decimal,
        target_price: Decimal,
        shares: int,
        ts: datetime,
    ) -> None:
        """Record that a position has been opened (post-fill callback)."""
        s = self._state(symbol)
        s.position = PositionSnapshot(
            symbol=symbol,
            entry_price=entry_price,
            current_stop=stop_price,
            target_price=target_price,
            shares=shares,
            entry_ts=ts,
            high_watermark=entry_price,
        )

    def close_position(self, symbol: str) -> None:
        """Record that a position has been fully closed."""
        self._state(symbol).position = None

    def update_stop(self, symbol: str, new_stop: Decimal) -> None:
        """Move the mental stop (e.g., to breakeven after P5 scale-out)."""
        s = self._state(symbol)
        if s.position is not None:
            s.position = PositionSnapshot(
                symbol=s.position.symbol,
                entry_price=s.position.entry_price,
                current_stop=new_stop,
                target_price=s.position.target_price,
                shares=s.position.shares,
                entry_ts=s.position.entry_ts,
                high_watermark=s.position.high_watermark,
            )

    def set_halted_resume(self, symbol: str, value: bool = True) -> None:
        """Mark that the symbol has just resumed from a halt (§12A)."""
        self._state(symbol).is_halted_resume = value

    def set_market_rank(self, symbol: str, rank: int | None) -> None:
        """Update the market %-gain rank (feeds P8 lost-popularity check)."""
        self._state(symbol).market_rank = rank

    # ──────────────────────────────────────────────────────────────────────────
    # Main bar processor
    # ──────────────────────────────────────────────────────────────────────────

    def on_bar(
        self,
        bar: BarTick,
        scan_result: ScanResult,
        l2_signal: L2Signal,
        spread: Decimal,
        market_state: MarketState,
    ) -> list[Signal]:
        """Process one bar.  Returns a (possibly empty) list of signals.

        10-sec bars update indicators and intraday_high but don't generate
        entry/exit decisions (those run on 1-min bars per spec §4A/§7).
        """
        s = self._state(bar.symbol)
        signals: list[Signal] = []

        # ── Update indicators on every bar ────────────────────────────────────
        macd_pt: MacdPoint | None = s.macd_state.update(bar.close)
        ema9_val = s.ema9_state.update(bar.close)
        vwap_val = s.vwap_state.update(bar.high, bar.low, bar.close, bar.volume)

        # Persist intraday high.
        if bar.high > s.intraday_high:
            s.intraday_high = bar.high

        # Route into the right window.
        if bar.timeframe == "1m":
            s.bars_1m.append(bar)
            if len(s.bars_1m) > _BAR_WINDOW:
                s.bars_1m.pop(0)
        elif bar.timeframe == "10s":
            s.bars_10s.append(bar)
            if len(s.bars_10s) > _10S_WINDOW:
                s.bars_10s.pop(0)
            return signals  # 10s bars don't drive decisions in Phase 2
        else:
            return signals  # unknown timeframe — ignore

        # From here on: only 1m bars.
        bars = s.bars_1m

        # ── In position: run exit engine ─────────────────────────────────────
        if s.position is not None:
            # Update high-watermark inside the position snapshot.
            if bar.close > s.position.high_watermark:
                s.position = PositionSnapshot(
                    symbol=s.position.symbol,
                    entry_price=s.position.entry_price,
                    current_stop=s.position.current_stop,
                    target_price=s.position.target_price,
                    shares=s.position.shares,
                    entry_ts=s.position.entry_ts,
                    high_watermark=bar.close,
                )

            exit_sig = evaluate_exit(
                position=s.position,
                current_bar=bar,
                prev_bars=bars[:-1],
                current_price=bar.close,
                l2_signal=l2_signal,
                vwap=vwap_val,
                market_rank=s.market_rank,
                intraday_high=s.intraday_high,
                config=self._cfg,
            )
            if exit_sig is not None:
                signals.append(exit_sig)
                if exit_sig.action == ScaleAction.FULL_EXIT:
                    s.position = None
            return signals

        # ── Not in position: evaluate entry gate ─────────────────────────────
        gate = evaluate_entry_gate(
            scan_result=scan_result,
            bars_1m=bars,
            macd_point=macd_pt,
            l2_signal=l2_signal,
            spread=spread,
            vwap=vwap_val,
            ema9=ema9_val,
            market_state=market_state,
            config=self._cfg,
        )

        if gate.passes:
            ctx = gate.pullback_ctx
            assert ctx is not None  # guaranteed by gate.passes == True

            pattern_match = recognize_pattern(
                bars,
                ctx,
                vwap=vwap_val,
                ema9=ema9_val,
                is_halted_resume=s.is_halted_resume,
                recent_reverse_split=scan_result.candidate.recent_reverse_split,
                prev_close=s.prev_close,
                gap_pct=s.gap_pct,
                flag_consolidation_max=self._cfg.get_decimal("FLAG_CONSOLIDATION_MAX"),
            )

            conviction = score_conviction(
                pattern=pattern_match.pattern,
                rvol=scan_result.candidate.rvol or Decimal("0"),
                float_shares=scan_result.candidate.float_shares,
                attention=scan_result.attention,
                spread=spread,
                retrace_ratio=ctx.retrace_ratio,
                ema9=ema9_val,
                current_price=bar.close,
                vwap=vwap_val,
            )

            # ── Compute stop and target ──────────────────────────────────────
            stop_basis_str = self._cfg.get_str("STOP_BASIS")
            if stop_basis_str == StopBasis.PREV_CANDLE_LOW.value and len(bars) >= 2:
                stop_price = bars[-2].low  # prev-candle-low (micro variant, C5)
            else:
                stop_price = ctx.pullback_low  # pullback_low (default, C5)

            entry_price = bar.close  # ask+offset applied by execution layer
            risk = entry_price - stop_price
            if risk <= Decimal("0"):
                risk = _TINY  # safety guard (should not happen post-E5)
            target_price = entry_price + _TWO * risk  # 2:1 RR minimum (spec §5)

            signals.append(
                EntrySignal(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    pattern=pattern_match.pattern,
                    conviction_score=conviction,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    gate=gate,
                    market_state=market_state,
                    vwap=vwap_val,
                    ema9=ema9_val,
                )
            )
        else:
            # Gate failed — check if we should emit a failed-pattern warning.
            ctx = gate.pullback_ctx
            if ctx is not None:
                lv_ratio = self._cfg.get_decimal("LIGHT_VOLUME_RATIO")
                lv_lookback = self._cfg.get_int("VOLUME_SPIKE_LOOKBACK")
                failed, reason = is_failed_pattern(
                    bars=bars,
                    vwap=vwap_val,
                    ema9=ema9_val,
                    macd_point=macd_pt,
                    retrace_ratio=ctx.retrace_ratio,
                    light_volume_ratio=lv_ratio,
                    volume_spike_lookback=lv_lookback,
                )
                if failed:
                    signals.append(
                        FailedPatternSignal(symbol=bar.symbol, ts=bar.ts, reason=reason)
                    )

        return signals

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────

    def _state(self, symbol: str) -> SymbolState:
        return self._states.setdefault(symbol, SymbolState())


__all__ = ["Signal", "StrategyEngine", "SymbolState"]
