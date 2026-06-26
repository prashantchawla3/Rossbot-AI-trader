"""Core backtest package — event-driven replay, conservative fills, U6 gate.

Phase 4: Paper Trading & Backtesting.
spec Phase 4 plan / ROSSBOT_PROJECT_PLAN.md Phase 4.
"""

from core.backtest.fill_model import (
    FILL_MODEL_DOC,
    MENTAL_STOP_LATENCY_SLIP,
    FillResult,
    entry_fill,
    exit_fill_stop,
    exit_fill_target,
)
from core.backtest.metrics import BacktestMetrics, compute_metrics
from core.backtest.models import BacktestResult, SimDay, TradeRecord
from core.backtest.paper_session import PaperSession
from core.backtest.replay import ReplayBar, replay
from core.backtest.sim_gate import SimulatorGate

__all__ = [
    # models
    "BacktestResult",
    "SimDay",
    "TradeRecord",
    # fill model
    "FILL_MODEL_DOC",
    "MENTAL_STOP_LATENCY_SLIP",
    "FillResult",
    "entry_fill",
    "exit_fill_stop",
    "exit_fill_target",
    # metrics
    "BacktestMetrics",
    "compute_metrics",
    # replay
    "ReplayBar",
    "replay",
    # U6 gate
    "SimulatorGate",
    # paper session
    "PaperSession",
]
