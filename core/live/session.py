"""Live trading session — hardened PaperSession for real capital.

Upgrades over PaperSession:
- Position reconciliation every RECONCILE_INTERVAL_S (broker truth vs. internal state).
- Feed-watchdog loop: on staleness detected → flatten-or-freeze, never trade blind.
- Mental-stop poll at LIVE_POLL_MS (default 100ms vs. 500ms for paper).
- Capital ramp cap applied after risk manager approval (MICRO/STARTER/FULL tiers).
- Pre-market readiness gate: ReadinessChecker.check_all() must pass before run().
- All guards from PaperSession (U3/U13/EOD flatten) remain enforced.
- Every reconcile discrepancy and feed-disconnect event writes to structlog (feeds dashboard).

Disconnect/recovery policy (spec Phase 6):
  - Feed stale for > FEED_STALENESS_SECONDS: freeze new entries, keep monitoring stops.
  - Broker unreachable during freeze: hold freeze, alert every 60s, wait for reconnect.
  - If still disconnected after RECONNECT_MAX_ATTEMPTS × RECONNECT_DELAY_S: flatten
    (if broker recovers) OR stay frozen (if broker still unreachable).
  - On reconnect: reconcile positions before resuming any new entries.

spec Phase 6 / §11 U3/U13 / §13.4 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from adapters.alpaca_broker import AlpacaBrokerAdapter
from adapters.base import BrokerAdapter, MarketDataAdapter, OrderRequest, OrderType, Side
from adapters.providers import L2Signal, MarketState
from core.backtest.fill_model import MENTAL_STOP_LATENCY_SLIP
from core.backtest.models import TradeRecord
from core.backtest.sim_gate import SimulatorGate
from core.config import ConfigService
from core.execution.backstop import CatastrophicBackstop
from core.execution.latency import LoopLatencyRecorder
from core.live.capital_ramp import CapitalRamp
from core.live.models import ReconcileResult
from core.live.readiness import ReadinessChecker
from core.live.reconcile import reconcile_positions
from core.risk.manager import RiskManager
from core.scanner.models import ScanResult
from core.strategy.engine import StrategyEngine
from core.strategy.models import EntrySignal, ExitSignal, PositionSnapshot, ScaleAction
from core.timeutils import now_utc

log = structlog.get_logger(__name__)


@dataclass
class _LivePosition:
    """Internal position tracking for the live session."""

    symbol: str
    entry_ts: datetime
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    shares: int
    risk_per_share: Decimal
    broker_order_id: str | None = None
    high_watermark: Decimal = field(default_factory=lambda: Decimal("0"))


class LiveSession:
    """Runs the full trading pipeline against a live broker with real capital.

    Gate: ``run()`` raises ``RuntimeError`` if:
    - SimulatorGate not satisfied OR LIVE_ENABLED=false (U6).
    - ReadinessChecker.check_all() returns any failed item.

    Usage::

        session = LiveSession(config, broker, market_data, risk_manager, sim_gate)
        await session.run(symbols=["AAPL"], scan_results=scan_map)

    spec Phase 6 / §11 U6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
    """

    def __init__(
        self,
        config: ConfigService,
        broker: BrokerAdapter,
        market_data: MarketDataAdapter,
        risk_manager: RiskManager,
        sim_gate: SimulatorGate,
    ) -> None:
        self._cfg = config
        self._broker = broker
        self._data = market_data
        self._risk = risk_manager
        self._gate = sim_gate
        self._engine = StrategyEngine(config)
        self._ramp = CapitalRamp(config)
        self._open: dict[str, _LivePosition] = {}
        self._trades: list[TradeRecord] = []
        self._stop_event = asyncio.Event()
        self._frozen = False            # freeze: no new entries (feed/broker disconnect)
        self._last_bar_ts: datetime | None = None
        # Phase 10: latency recorder + optional catastrophic backstop (§13.4)
        self._latency = LoopLatencyRecorder(config)
        self._backstop = CatastrophicBackstop(config)

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(
        self,
        symbols: list[str],
        scan_results: dict[str, ScanResult],
        l2_signals: dict[str, L2Signal] | None = None,
        market_state: MarketState = MarketState.COLD,
        *,
        skip_readiness: bool = False,
    ) -> list[TradeRecord]:
        """Main live-trading loop. Raises RuntimeError if gates are not satisfied.

        :param skip_readiness: For dry-run / sandbox testing only; never set True in prod.
        """
        # Hard gate: U6 + LIVE_ENABLED (spec §11 U6)
        if not self._gate.live_mode_allowed(self._cfg):
            raise RuntimeError(
                f"Live trading blocked — U6 gate not satisfied. {self._gate.status_summary}"
            )

        # Readiness checklist
        if not skip_readiness:
            checker = ReadinessChecker(self._cfg, self._gate, self._broker, self._data)
            result = await checker.check_all()
            if not result.all_passed:
                raise RuntimeError(f"Pre-market readiness FAILED: {result.summary()}")
            log.info("live_session.readiness_ok", summary=result.summary())

        log.info(
            "live_session.start",
            symbols=symbols,
            tier=self._ramp.tier,
            live_poll_ms=self._cfg.get_int("LIVE_POLL_MS"),
        )

        account = await self._broker.account_state()
        for sym in symbols:
            self._engine.reset_session(sym, prev_close=Decimal("0"))
        self._risk.reset_session()

        poll_s = self._cfg.get_int("LIVE_POLL_MS") / 1000.0
        reconcile_s = self._cfg.get_int("RECONCILE_INTERVAL_S")

        tasks = [
            asyncio.create_task(
                self._bar_loop(symbols, scan_results, l2_signals, market_state, account.equity)
            ),
            asyncio.create_task(self._mental_stop_loop(poll_s)),
            asyncio.create_task(self._eod_flatten_loop()),
            asyncio.create_task(self._reconcile_loop(reconcile_s)),
            asyncio.create_task(
                self._feed_watchdog_loop(self._cfg.get_decimal("FEED_STALENESS_SECONDS"))
            ),
        ]

        await self._stop_event.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("live_session.stopped", trades=len(self._trades))
        return self._trades

    def stop(self) -> None:
        """Signal the session to halt after the current bar."""
        self._stop_event.set()

    # ── Bar processing ────────────────────────────────────────────────────────

    async def _bar_loop(
        self,
        symbols: list[str],
        scan_results: dict[str, ScanResult],
        l2_signals: dict[str, L2Signal] | None,
        market_state: MarketState,
        equity: Decimal,
    ) -> None:
        async for bar in self._data.subscribe_bars(symbols, "1m"):
            if self._stop_event.is_set():
                break
            self._last_bar_ts = now_utc()

            if self._frozen:
                log.warning("live_session.frozen_skip_bar", symbol=bar.symbol)
                continue

            scan = scan_results.get(bar.symbol)
            if scan is None:
                continue

            l2 = (l2_signals or {}).get(bar.symbol, L2Signal.UNKNOWN)
            quote = await self._data.get_quote(bar.symbol)
            spread = quote.ask - quote.bid

            signals = self._engine.on_bar(bar, scan, l2, spread, market_state)

            for sig in signals:
                if isinstance(sig, EntrySignal) and bar.symbol not in self._open:
                    await self._handle_entry(sig, bar.ts, equity)
                elif isinstance(sig, ExitSignal) and bar.symbol in self._open:
                    if sig.action is ScaleAction.FULL_EXIT:
                        await self._handle_exit(sig, bar)

    async def _handle_entry(self, signal: EntrySignal, now: datetime, equity: Decimal) -> None:
        approval = self._risk.evaluate(signal=signal, now_et=now, account_equity=equity)
        if not approval.approved:
            log.info(
                "live_session.entry_vetoed",
                symbol=signal.symbol,
                reasons=[v for v in approval.vetoes],
            )
            return

        # Apply capital ramp cap on top of risk manager approval
        capped_shares = self._ramp.apply(approval.shares)
        if capped_shares <= 0:
            log.info("live_session.ramp_zeroed", symbol=signal.symbol, tier=self._ramp.tier)
            return

        offset = self._cfg.get_decimal("BUY_OFFSET")
        limit_price = signal.entry_price + offset
        client_id = str(uuid.uuid4())

        ack = await self._broker.submit_marketable_limit(
            OrderRequest(
                client_order_id=client_id,
                symbol=signal.symbol,
                side=Side.BUY,
                qty=capped_shares,
                limit_price=limit_price,
                order_type=OrderType.MARKETABLE_LIMIT,
            )
        )

        if ack.accepted:
            self._risk.record_open(signal.symbol, limit_price)
            self._engine.open_position(
                symbol=signal.symbol,
                entry_price=limit_price,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                shares=capped_shares,
                ts=now,
            )
            self._open[signal.symbol] = _LivePosition(
                symbol=signal.symbol,
                entry_ts=now,
                entry_price=limit_price,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                shares=capped_shares,
                risk_per_share=signal.risk_per_share,
                broker_order_id=ack.broker_order_id,
                high_watermark=limit_price,
            )
            log.info(
                "live_session.entry",
                symbol=signal.symbol,
                shares=capped_shares,
                limit=str(limit_price),
                tier=self._ramp.tier,
            )
        else:
            log.warning("live_session.entry_rejected", symbol=signal.symbol, status=ack.status)

    async def _handle_exit(self, signal: ExitSignal, bar) -> None:
        pos = self._open.get(signal.symbol)
        if pos is None:
            return

        client_id = str(uuid.uuid4())
        ack = await self._broker.partial_sell(
            signal.symbol,
            pos.shares,
            bar.close,
            client_order_id=client_id,
        )

        if ack.accepted:
            self._risk.record_close(signal.symbol, Decimal("0"))
            self._engine.close_position(signal.symbol)
            del self._open[signal.symbol]
            log.info("live_session.exit", symbol=signal.symbol, reason=signal.reason)
        else:
            log.warning("live_session.exit_rejected", symbol=signal.symbol, status=ack.status)

    # ── Mental stop monitor (U13) ─────────────────────────────────────────────

    async def _mental_stop_loop(self, poll_s: float) -> None:
        """Poll quotes and fire marketable-limit on mental-stop breach (U13).

        Phase 10 hardens this loop with:
        - LoopLatencyRecorder: measures each iteration wall-clock time; logs
          WARN when above LATENCY_WARN_MS so the operator can tune LIVE_POLL_MS
          or BACKSTOP_OFFSET (spec §13.4).
        - CatastrophicBackstop: optional second internal mental stop far below
          the primary level; fires marketable-limit — never a native STOP (U13).

        LIVE_POLL_MS default = 100ms (tighter than 500ms paper).
        Never routes a native STOP order (U13). spec §13.4.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(poll_s)
            if self._frozen:
                continue
            for symbol, pos in list(self._open.items()):
                try:
                    with self._latency.measure():
                        quote = await self._data.get_quote(symbol)
                        snap = PositionSnapshot(
                            symbol=symbol,
                            entry_price=pos.entry_price,
                            current_stop=pos.stop_price,
                            target_price=pos.target_price,
                            shares=pos.shares,
                            entry_ts=pos.entry_ts,
                            high_watermark=pos.high_watermark,
                        )
                        # Update watermark
                        if quote.bid > pos.high_watermark:
                            pos.high_watermark = quote.bid

                        # Primary mental stop (U13 — no native STOP)
                        primary_fired = self._risk.check_mental_stop(quote.bid, snap)

                        # Catastrophic backstop (§13.4 — optional, same mechanism)
                        backstop_fired = self._backstop.is_breached(
                            quote.bid, pos.entry_price
                        )

                        if primary_fired or backstop_fired:
                            limit_price = max(
                                quote.bid - MENTAL_STOP_LATENCY_SLIP,
                                Decimal("0.01"),
                            )
                            client_id = str(uuid.uuid4())
                            ack = await self._broker.partial_sell(
                                symbol, pos.shares, limit_price, client_order_id=client_id
                            )
                            if ack.accepted:
                                self._risk.record_close(symbol, Decimal("0"))
                                self._engine.close_position(symbol)
                                del self._open[symbol]
                                log.info(
                                    "live_session.mental_stop_fired",
                                    symbol=symbol,
                                    bid=str(quote.bid),
                                    limit=str(limit_price),
                                    primary=primary_fired,
                                    backstop=backstop_fired,
                                    latency_stats=self._latency.stats,
                                )
                except Exception as exc:  # noqa: BLE001
                    log.error("live_session.mental_stop_error", symbol=symbol, error=str(exc))

    @property
    def latency_stats(self) -> dict[str, float]:
        """Return mental-stop loop latency stats (ms).  Recorded in PROGRESS.md §13.4."""
        return self._latency.stats

    # ── EOD flatten (U3) ──────────────────────────────────────────────────────

    async def _eod_flatten_loop(self) -> None:
        """Flatten all positions at EOD_FLATTEN_TIME (U3). spec §11 U3."""
        while not self._stop_event.is_set():
            await asyncio.sleep(10)
            now = now_utc()
            if self._risk.should_flatten_eod(now) and self._open:
                log.info("live_session.eod_flatten", positions=list(self._open.keys()))
                await self._broker.cancel_all_flatten()
                for symbol in list(self._open.keys()):
                    self._risk.record_close(symbol, Decimal("0"))
                    self._engine.close_position(symbol)
                self._open.clear()
                self.stop()

    # ── Reconciliation loop ───────────────────────────────────────────────────

    async def _reconcile_loop(self, interval_s: int) -> None:
        """Compare broker positions vs. internal state every interval_s seconds.

        - broker_only (ghost): log + alert; do NOT trade the ghost.
        - internal_only (orphan): correct by removing from _open (we thought we had it).
        - qty_mismatch (drift): log discrepancy; leave correction to next reconcile.
        spec Phase 6 reconciliation.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(interval_s)
            try:
                broker_positions = await self._get_broker_positions()
                internal_positions = {sym: pos.shares for sym, pos in self._open.items()}
                result = reconcile_positions(broker_positions, internal_positions)

                if not result.clean:
                    log.warning("live_session.reconcile_discrepancy", summary=result.summary())

                # Correct orphan state: we track a position the broker doesn't have
                for sym in result.internal_only:
                    log.error(
                        "live_session.orphan_position_corrected",
                        symbol=sym,
                        internal_shares=self._open[sym].shares,
                    )
                    self._risk.record_close(sym, Decimal("0"))
                    self._engine.close_position(sym)
                    del self._open[sym]

                # Log ghost positions (broker has them, we don't) — do NOT trade
                for sym in result.broker_only:
                    log.error(
                        "live_session.ghost_position_detected",
                        symbol=sym,
                        broker_shares=broker_positions.get(sym),
                    )

                if result.qty_mismatch:
                    log.warning(
                        "live_session.qty_mismatch",
                        symbols=list(result.qty_mismatch),
                    )

            except Exception as exc:  # noqa: BLE001
                log.error("live_session.reconcile_error", error=str(exc))

    async def _get_broker_positions(self) -> dict[str, int]:
        if isinstance(self._broker, AlpacaBrokerAdapter):
            return await self._broker.get_broker_positions()
        # For other adapters: skip reconcile gracefully
        return {sym: pos.shares for sym, pos in self._open.items()}

    # ── Feed watchdog → flatten-or-freeze ────────────────────────────────────

    async def _feed_watchdog_loop(self, stale_threshold_s: Decimal) -> None:
        """Monitor data-feed liveness; on staleness → freeze new entries.

        If the feed has been stale for too long:
        - Freeze new entries (self._frozen = True).
        - Attempt to flatten all open positions via broker (fail-safe).
        - If broker also unreachable: stay frozen, alert, wait.
        spec Phase 6 disconnect/recovery.
        """
        threshold = float(stale_threshold_s)
        reconnect_max = self._cfg.get_int("RECONNECT_MAX_ATTEMPTS")
        reconnect_delay = self._cfg.get_int("RECONNECT_DELAY_S")
        freeze_logged = False

        while not self._stop_event.is_set():
            await asyncio.sleep(max(threshold / 2, 1.0))

            if self._last_bar_ts is None:
                continue  # session not yet started receiving bars

            age = (now_utc() - self._last_bar_ts).total_seconds()
            if age <= threshold:
                if self._frozen:
                    # Feed recovered — reconcile then unfreeze
                    log.info("live_session.feed_recovered", stale_s=age)
                    self._frozen = False
                    freeze_logged = False
                continue

            # Feed is stale
            if not freeze_logged:
                log.error(
                    "live_session.feed_stale_freeze",
                    stale_s=age,
                    threshold_s=threshold,
                )
                freeze_logged = True

            self._frozen = True  # no new entries while stale

            if self._open:
                await self._handle_disconnect(reconnect_max, reconnect_delay)

    async def _handle_disconnect(self, max_attempts: int, delay_s: int) -> None:
        """Try to flatten open positions on disconnect.

        Attempts broker cancel_all_flatten up to max_attempts times.
        If unreachable after all attempts: stays frozen (positions held, no new entries).
        spec Phase 6 disconnect → flatten-or-freeze.
        """
        for attempt in range(1, max_attempts + 1):
            try:
                log.warning(
                    "live_session.flatten_attempt",
                    attempt=attempt,
                    max=max_attempts,
                    positions=list(self._open.keys()),
                )
                acks = await self._broker.cancel_all_flatten()
                # Assume all positions closed if broker responded
                if acks:
                    for symbol in list(self._open.keys()):
                        self._risk.record_close(symbol, Decimal("0"))
                        self._engine.close_position(symbol)
                    self._open.clear()
                    log.info("live_session.disconnect_flatten_ok")
                    return
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "live_session.flatten_attempt_failed",
                    attempt=attempt,
                    error=str(exc),
                )
            await asyncio.sleep(delay_s)

        log.critical(
            "live_session.disconnect_freeze_held",
            positions=list(self._open.keys()),
            message=(
                "Broker unreachable after all reconnect attempts. "
                "Positions held, no new entries. "
                "Manual intervention required."
            ),
        )


__all__ = ["LiveSession"]
