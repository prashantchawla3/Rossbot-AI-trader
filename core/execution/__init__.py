"""Execution-safety package (spec §13.4 / §13.5, Phase 10).

Hardens the no-native-stop path with:
  - Breakout-or-bailout (quantified time stop, §3 P2 / §13.5)
  - Optional catastrophic backstop far below primary mental stop (§13.4)
  - Loop latency recorder for the mental-stop monitor (§13.4)

Public API:
  has_higher_high_on_rising_volume  — pure: momentum guard for bailout
  is_bailout_condition              — pure: full time-stop gate
  CatastrophicBackstop              — optional second internal mental stop
  LoopLatencyRecorder               — wall-clock latency tracker
"""

from core.execution.backstop import CatastrophicBackstop
from core.execution.bailout import has_higher_high_on_rising_volume, is_bailout_condition
from core.execution.latency import LoopLatencyRecorder

__all__ = [
    "CatastrophicBackstop",
    "LoopLatencyRecorder",
    "has_higher_high_on_rising_volume",
    "is_bailout_condition",
]
