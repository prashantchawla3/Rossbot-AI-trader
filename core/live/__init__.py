"""Phase 6 — Live Trading layer.

Hardened execution path for real capital. Import order:
  models → reconcile → capital_ramp → readiness → session

All live trading is gated by:
  1. U6 simulator gate (SimulatorGate.satisfied + LIVE_ENABLED=true in config)
  2. ReadinessChecker.check_all() → all_passed=True
  3. CAPITAL_RAMP_TIER starts at MICRO (manually promoted by client after review)

spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from core.live.capital_ramp import CapitalRamp, CapitalTier
from core.live.models import ReadinessItem, ReadinessResult, ReconcileResult
from core.live.readiness import ReadinessChecker
from core.live.reconcile import reconcile_positions
from core.live.session import LiveSession

__all__ = [
    "CapitalRamp",
    "CapitalTier",
    "LiveSession",
    "ReadinessChecker",
    "ReadinessItem",
    "ReadinessResult",
    "ReconcileResult",
    "reconcile_positions",
]
