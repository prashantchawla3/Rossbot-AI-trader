"""Pydantic response schemas for the trading performance dashboard.

All monetary fields are strings (Decimal → str) matching the dashboard convention
in api/schemas/dashboard.py.  No float money.  spec §4 (patterns), §3 (exit rules).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class EquityPoint(_Out):
    ts: str
    cumulative_pnl: str
    trade_id: int


class DailyPnL(_Out):
    date: str
    pnl: str


class TradeLogEntry(_Out):
    trade_id: int
    symbol: str
    side: str
    pattern_type: str
    entry_price: str
    exit_price: str
    shares: int
    realized_pnl: str
    r_multiple: float | None
    exit_reason: str
    is_disciplined: bool
    entry_ts: str
    exit_ts: str
    day_pnl_running_total: str


class TradesResponse(_Out):
    trades: list[TradeLogEntry]
    total: int
    page: int
    page_size: int
    pages: int


class ScanRejection(_Out):
    symbol: str
    pillars_failed: list[str]


class ScanStats(_Out):
    symbols_scanned: int
    tier_a_count: int
    tier_b_count: int
    rejected_from_tier_b: list[ScanRejection]


class PerformanceSummary(_Out):
    total_trades: int
    win_count: int
    loss_count: int
    win_rate_value: float | None
    win_rate_str: str
    avg_r_winners: float | None
    avg_r_losers: float | None
    max_drawdown_pct: float
    give_back_pct_from_peak: float
    rule_violation_count: int
    rolling_5_win_rate: float | None
    rolling_20_win_rate: float | None
    equity_curve: list[EquityPoint]
    daily_pnl: list[DailyPnL]
    realized_pnl: str
    peak_pnl: str
    max_daily_loss_limit: str
    give_back_warn_pct: float
    give_back_hard_pct: float


__all__ = [
    "DailyPnL",
    "EquityPoint",
    "PerformanceSummary",
    "ScanRejection",
    "ScanStats",
    "TradeLogEntry",
    "TradesResponse",
]
