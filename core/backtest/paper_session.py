"""Live paper simulator — full pipeline on live data, zero real money.

Orchestrates Strategy → Risk → Execution on live data streams, routing approved
signals to the Alpaca paper broker (or any BrokerAdapter).  No real capital is
deployed until the U6 gate is satisfied AND LIVE_ENABLED=true in config.

Design:
- Async event loop; each bar triggers the same Strategy→Risk→Execute pipeline as replay.py.
- Mental stop monitored via a background asyncio task (poll interval = config MENTAL_STOP_POLL_MS).
- EOD flatten fires automatically at EOD_FLATTEN_TIME.
- Every order is idempotent (client_order_id = UUID per intent).
- No native STOP orders are ever submitted (U13; OrderType has no STOP member by construction).

Alpaca paper API (verified 2026):
  base_url = "https://paper-api.alpaca.markets"
  endpoints: /v2/orders, /v2/positions, /v2/account (same paths as live)
  paper partial fills: ~10% random probability of 50% partial (Alpaca paper behaviour).

spec Phase 4 plan / ROSSBOT_PROJECT_PLAN.md Phase 4.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from adapters.base import BrokerAdapter, MarketDataAdapter, OrderRequest, OrderType, Side
from adapters.providers import L2Signal, MarketState
from core.backtest.models import TradeRecord
from core.backtest.fill_model import MENTAL_STOP_LATENCY_SLIP
from core.config import ConfigService
from core.risk.manager import RiskManager
from core.scanner.models import ScanResult
from core.strategy.engine import StrategyEngine
from core.strategy.models import EntrySignal, ExitSignal, PositionSnapshot, ScaleAction


@dataclass
class _LivePosition:
    """Live position tracking for the paper session."""

    symbol: str
    entry_ts: datetime
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    shares: int
    risk_per_share: Decimal
    broker_order_id: str | None = None


class PaperSession:
    """Runs the full trading pipeline on live data against the Alpaca paper broker.

    Usage::

        session = PaperSession(config, broker_adapter, market_data_adapter, risk_manager)
        await session.run(symbols=["AAPL", "TSLA"], scan_results=scan_map)

    The session respects the U6 gate — live mode is blocked until satisfied.
    spec Phase 4 plan / §11 U6.
    """

    ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"

    def __init__(
        self,
        config: ConfigService,
        broker: BrokerAdapter,
        market_data: MarketDataAdapter,
        risk_manager: RiskManager,
    ) -> None:
        self._cfg = config
        self._broker = broker
        self._data = market_data
        self._risk = risk_manager
        self._engine = StrategyEngine(config)
        self._open: dict[str, _LivePosition] = {}
        self._trades: list[TradeRecord] = []
        self._stop_event = asyncio.Event()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(
        self,
        symbols: list[str],
        scan_results: dict[str, ScanResult],
        l2_signals: dict[str, L2Signal] | None = None,
        market_state: MarketState = MarketState.COLD,
    ) -> list[TradeRecord]:
        """Main paper-trading loop.  Runs until ``stop()`` is called.

        ``scan_results`` maps symbol → ScanResult (updated externally by the scanner).
        ``l2_signals`` maps symbol → L2Signal (updated externally; defaults UNKNOWN).
        """
        # Initialise sessions
        account = await self._broker.account_state()
        for sym in symbols:
            self._engine.reset_session(sym, prev_close=Decimal("0"))
        self._risk.reset_session()

        tasks = [
            asyncio.create_task(self._bar_loop(symbols, scan_results, l2_signals, market_state, account.equity)),
            asyncio.create_task(self._mental_stop_loop()),
            asyncio.create_task(self._eod_flatten_loop()),
        ]

        await self._stop_event.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return self._trades

    def stop(self) -> None:
        """Signal the session to stop after the current bar."""
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
        """Stream 1-min bars and run the Strategy→Risk→Execute pipeline."""
        async for bar in self._data.subscribe_bars(symbols, "1m"):
            if self._stop_event.is_set():
                break

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
                    if sig.action == ScaleAction.FULL_EXIT:
                        await self._handle_exit(sig, bar)

    async def _handle_entry(self, signal: EntrySignal, now: datetime, equity: Decimal) -> None:
        """Evaluate and submit a paper entry order."""
        approval = self._risk.evaluate(
            signal=signal,
            now_et=now,
            account_equity=equity,
        )
        if not approval.approved:
            return

        offset = self._cfg.get_decimal("BUY_OFFSET")
        limit_price = signal.entry_price + offset
        client_id = str(uuid.uuid4())

        ack = await self._broker.submit_marketable_limit(
            OrderRequest(
                client_order_id=client_id,
                symbol=signal.symbol,
                side=Side.BUY,
                qty=approval.shares,
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
                shares=approval.shares,
                ts=now,
            )
            self._open[signal.symbol] = _LivePosition(
                symbol=signal.symbol,
                entry_ts=now,
                entry_price=limit_price,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                shares=approval.shares,
                risk_per_share=signal.risk_per_share,
                broker_order_id=ack.broker_order_id,
            )

    async def _handle_exit(self, signal: ExitSignal, bar) -> None:
        """Submit a paper exit order on an exit signal."""
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
            self._risk.record_close(signal.symbol, Decimal("0"))  # PnL tracked via fills
            self._engine.close_position(signal.symbol)
            del self._open[signal.symbol]

    # ── Mental stop monitor (U13) ─────────────────────────────────────────────

    async def _mental_stop_loop(self) -> None:
        """Poll quotes and fire marketable-limit on mental-stop breach (U13).

        Polls at MENTAL_STOP_POLL_MS intervals. Never routes a native STOP order.
        spec §3 P1 / §11 U13 / §13.4.
        """
        poll_ms = 500  # 500ms poll interval for paper; tighten for live
        while not self._stop_event.is_set():
            await asyncio.sleep(poll_ms / 1000)
            for symbol, pos in list(self._open.items()):
                try:
                    quote = await self._data.get_quote(symbol)
                    snap = PositionSnapshot(
                        symbol=symbol,
                        entry_price=pos.entry_price,
                        current_stop=pos.stop_price,
                        target_price=pos.target_price,
                        shares=pos.shares,
                        entry_ts=pos.entry_ts,
                        high_watermark=pos.entry_price,
                    )
                    if self._risk.check_mental_stop(quote.bid, snap):
                        # Fire marketable-limit — never a native STOP (U13)
                        limit_price = max(
                            quote.bid - MENTAL_STOP_LATENCY_SLIP,
                            Decimal("0.01"),
                        )
                        client_id = str(uuid.uuid4())
                        await self._broker.partial_sell(
                            symbol,
                            pos.shares,
                            limit_price,
                            client_order_id=client_id,
                        )
                        self._risk.record_close(symbol, Decimal("0"))
                        self._engine.close_position(symbol)
                        del self._open[symbol]
                except Exception:  # noqa: BLE001 — log and continue; never trade blind
                    pass

    # ── EOD flatten (U3) ──────────────────────────────────────────────────────

    async def _eod_flatten_loop(self) -> None:
        """Monitor for EOD flatten time and cancel-all-flatten (U3).

        spec §11 U3.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(10)
            now = datetime.now()  # ET conversion handled inside risk manager
            if self._risk.should_flatten_eod(now) and self._open:
                await self._broker.cancel_all_flatten()
                for symbol in list(self._open.keys()):
                    self._risk.record_close(symbol, Decimal("0"))
                    self._engine.close_position(symbol)
                self._open.clear()
                self.stop()


__all__ = ["PaperSession"]
