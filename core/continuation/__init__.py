"""Multi-day continuation engine — spec §12B / §13.10.

Eligibility: Day-1 move ≥100% AND held gains into close.
Done-conditions: RVOL<25% prior, retrace>50%, MACD cross, VWAP loss.
Auto-adjustments: 5-min timeframe + reduced size when active.
"""

from core.continuation.engine import (
    check_continuation_done,
    evaluate_day2_eligibility,
    get_day2_settings,
)
from core.continuation.models import (
    ContinuationContext,
    Day2Settings,
    DoneReason,
    EligibilityResult,
)

__all__ = [
    "ContinuationContext",
    "Day2Settings",
    "DoneReason",
    "EligibilityResult",
    "check_continuation_done",
    "evaluate_day2_eligibility",
    "get_day2_settings",
]
