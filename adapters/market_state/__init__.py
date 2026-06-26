"""Market-state classifier package (spec §8 / §13.9, Phase 9).

Replaces StubMarketStateProvider (always COLD) with a real rolling-feature
HOT/COLD/REHAB classifier.  Bias COLD on uncertainty.

Public API:
  DaySnapshot                — one day's breadth data (input to classifier)
  MarketStateFeatures        — aggregate rolling features
  compute_features           — pure: list[DaySnapshot] → MarketStateFeatures
  classify_market_state      — pure: MarketStateFeatures × cfg → MarketState
  score_attention            — pure: rank × rvol × cfg → float [0, 1]
  RollingMarketStateProvider — stateful provider (implements MarketStateProvider)
"""

from adapters.market_state.attention import score_attention
from adapters.market_state.classifier import classify_market_state
from adapters.market_state.features import compute_features
from adapters.market_state.models import DaySnapshot, MarketStateFeatures
from adapters.market_state.provider import RollingMarketStateProvider

__all__ = [
    "DaySnapshot",
    "MarketStateFeatures",
    "RollingMarketStateProvider",
    "classify_market_state",
    "compute_features",
    "score_attention",
]
