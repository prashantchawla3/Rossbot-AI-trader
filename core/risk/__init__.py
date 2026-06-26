"""Risk Management Layer — the mandatory gate between Strategy and Execution.

CLAUDE.md §3: "Risk Manager sits between Strategy and Execution as a mandatory gate.
No order reaches the broker without passing it. Strategy proposes; Risk disposes;
Execution obeys."

spec §5 (risk rules), §6 (sizing), §7 (time), §8 (market state), §11 (U1–U15).
"""

from core.risk.manager import RiskManager
from core.risk.models import GiveBackLevel, RiskState, TradeApproval, VetoReason

__all__ = [
    "GiveBackLevel",
    "RiskManager",
    "RiskState",
    "TradeApproval",
    "VetoReason",
]
