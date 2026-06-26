"""L2 / Tape Microstructure Engine (spec §2A / §13.2, Phase 8).

Replaces StubL2SignalProvider with real floor-vs-spoof, iceberg, green-tape,
and absorption/break detectors fed by Databento TotalView-ITCH depth + tape.

Public API:
  L2MicrostructureProvider  – implements L2SignalProvider; stateful accumulator
  DepthBook                 – rolling ring-buffer of DepthSnapshot per symbol
  TapeAccumulator           – rolling time-window of TapeTick per symbol
  detect_spoof              – pure function: large bid vanishes without prints
  detect_iceberg            – pure function: executed >> displayed, no advance
  detect_real_floor         – pure function: stable bid + prints confirm
  detect_absorb_break       – pure function: visible ask absorbed then break
"""

from adapters.l2.depth_book import DepthBook
from adapters.l2.detectors import (
    detect_absorb_break,
    detect_iceberg,
    detect_real_floor,
    detect_spoof,
)
from adapters.l2.models import DepthSnapshot, TapeAggregate
from adapters.l2.provider import L2MicrostructureProvider
from adapters.l2.tape_window import TapeAccumulator

__all__ = [
    "DepthBook",
    "DepthSnapshot",
    "L2MicrostructureProvider",
    "TapeAccumulator",
    "TapeAggregate",
    "detect_absorb_break",
    "detect_iceberg",
    "detect_real_floor",
    "detect_spoof",
]
