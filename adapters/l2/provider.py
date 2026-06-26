"""L2MicrostructureProvider — replaces StubL2SignalProvider (spec §2A / §13.2).

Stateful provider that accumulates Databento depth (MBP-10) + tape (trades)
events per symbol and returns an L2Signal when the strategy engine calls
evaluate().  Priority order: SPOOF/ICEBERG > ABSORB_BREAK > SUPPORT > UNKNOWN.

Usage (live session):
    provider = L2MicrostructureProvider(config)
    # Wire into Databento feed callbacks:
    provider.on_depth(depth_tick)
    provider.on_tape(tape_tick)
    # Entry gate calls:
    signal = await provider.evaluate(symbol)

spec §2A depth/tape reading / §13.2 automation notes / CLAUDE.md Phase 8.
"""

from __future__ import annotations

from adapters.base import DepthTick, TapeTick
from adapters.l2.depth_book import DepthBook
from adapters.l2.detectors import (
    detect_absorb_break,
    detect_iceberg,
    detect_real_floor,
    detect_spoof,
)
from adapters.l2.tape_window import TapeAccumulator
from adapters.providers import L2Signal, L2SignalProvider
from core.config import ConfigService


class L2MicrostructureProvider(L2SignalProvider):
    """Real L2/tape signal provider backed by Databento depth + tape streams.

    Replaces StubL2SignalProvider.  The live session must call on_depth() and
    on_tape() as ticks arrive; the strategy engine then calls evaluate() to
    get the current signal for a symbol.

    When no data is available for a symbol (book or tape not yet seeded), the
    provider returns UNKNOWN — fail closed (spec §13.2 / CLAUDE.md Rule C).

    spec §2A / §13.2 / CLAUDE.md Phase 8 / U14.
    """

    def __init__(self, config: ConfigService) -> None:
        self._cfg = config
        self._books: dict[str, DepthBook] = {}
        self._tapes: dict[str, TapeAccumulator] = {}

    # ── Feed ingestion ──────────────────────────────────────────────────────

    def on_depth(self, tick: DepthTick) -> None:
        """Ingest a Databento MBP-10 depth tick for the symbol."""
        sym = tick.symbol
        if sym not in self._books:
            self._books[sym] = DepthBook(
                max_snapshots=self._cfg.get_int("L2_DEPTH_SNAPSHOTS")
            )
        self._books[sym].add(tick)

    def on_tape(self, tick: TapeTick) -> None:
        """Ingest a Databento trades tick for the symbol."""
        sym = tick.symbol
        if sym not in self._tapes:
            self._tapes[sym] = TapeAccumulator(
                window_secs=self._cfg.get_int("L2_WINDOW_SECS")
            )
        self._tapes[sym].add(tick)

    def reset(self, symbol: str) -> None:
        """Clear accumulated state for a symbol (e.g. at EOD or symbol rotation)."""
        self._books.pop(symbol, None)
        self._tapes.pop(symbol, None)

    # ── Signal evaluation ───────────────────────────────────────────────────

    async def evaluate(self, symbol: str) -> L2Signal:
        """Run all detectors and return the highest-priority L2 signal.

        Returns UNKNOWN if the depth book or tape window has no data yet —
        fail closed per spec §13.2 (do not trade without L2 confirmation).

        Priority order (spec §2A):
          SPOOF or ICEBERG  → danger signals first (most conservative)
          ABSORB_BREAK      → bullish entry (E6 satisfied)
          SUPPORT           → real floor with prints (E6 satisfied)
          UNKNOWN           → insufficient data — E6 fails → no trade
        """
        book = self._books.get(symbol)
        tape = self._tapes.get(symbol)

        if book is None or tape is None:
            return L2Signal.UNKNOWN  # spec §13.2 fail-closed: no data → no trade

        snaps = book.snapshots()
        if not snaps:
            return L2Signal.UNKNOWN

        snap = snaps[-1]
        # Use the latest print timestamp as the "now" reference for window eviction
        agg = tape.aggregate(now=snap.ts)

        # ── Read config values once ──────────────────────────────────────────
        spoof_bid_min = self._cfg.get_int("SPOOF_BID_MIN_SHARES")
        spoof_decay = self._cfg.get_int("SPOOF_DECAY_SECS")
        spoof_min_prints = self._cfg.get_int("SPOOF_MIN_PRINTS")

        iceberg_absorbed = self._cfg.get_int("ICEBERG_ABSORBED_MIN")
        iceberg_display = self._cfg.get_int("ICEBERG_DISPLAY_MAX")
        iceberg_advance = self._cfg.get_int("ICEBERG_ADVANCE_MAX_CENTS")

        floor_bid_min = self._cfg.get_int("FLOOR_BID_MIN_SHARES")
        floor_min_prints = self._cfg.get_int("FLOOR_MIN_PRINTS")
        floor_stable = self._cfg.get_int("FLOOR_MIN_STABLE_SNAPS")

        absorb_ask_min = self._cfg.get_int("ABSORB_ASK_MIN_SHARES")
        absorb_tape_min = self._cfg.get_int("ABSORB_TAPE_MIN_SHARES")
        absorb_break_cents = self._cfg.get_int("ABSORB_BREAK_MIN_CENTS")

        # ── Detection priority: danger first ─────────────────────────────────

        # spec §2A EX4/EX6: fake bid → vanishes → avoid
        if detect_spoof(
            snaps,
            agg,
            spoof_bid_min_shares=spoof_bid_min,
            spoof_decay_secs=spoof_decay,
            spoof_min_prints=spoof_min_prints,
        ):
            return L2Signal.SPOOF

        # spec §2A GMBL/NIXX, U14: massive buying, price flat, small displayed ask
        if detect_iceberg(
            agg,
            snap,
            absorbed_min=iceberg_absorbed,
            display_max=iceberg_display,
            advance_max_cents=iceberg_advance,
        ):
            return L2Signal.ICEBERG

        # spec §2A absorbed-then-break → bullish trigger E6
        if detect_absorb_break(
            snaps,
            agg,
            absorb_ask_min_shares=absorb_ask_min,
            absorb_tape_min_shares=absorb_tape_min,
            absorb_break_min_cents=absorb_break_cents,
        ):
            return L2Signal.ABSORB_BREAK

        # spec §2A real floor: stacked bids + print confirmation → SUPPORT
        if detect_real_floor(
            snaps,
            agg,
            floor_bid_min_shares=floor_bid_min,
            floor_min_prints=floor_min_prints,
            floor_min_stable_snaps=floor_stable,
        ):
            return L2Signal.SUPPORT

        return L2Signal.UNKNOWN
