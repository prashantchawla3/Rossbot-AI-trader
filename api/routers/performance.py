"""Trading performance endpoints — spec Phase 5 / performance dashboard.

GET /api/performance/trades      — paginated trade log (from engine.closed_trades)
GET /api/performance/summary     — aggregate stats (equity curve, drawdown, win rate)
GET /api/performance/scan-stats  — scan rejection breakdown (drives the empty-state screen)

All endpoints return clean empty/zero data when no trades have executed yet — the
frontend renders that as "no trades yet" rather than an error or blank screen.

WebSocket /ws/performance is registered in api/main.py (shares the perf_ws_manager).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/trades")
async def get_performance_trades(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    symbol: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Paginated trade log filterable by symbol and date range.

    Returns empty list when no trades have executed — never raises on zero trades.
    date_from / date_to are ISO date strings (YYYY-MM-DD).
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    eng = getattr(request.app.state, "demo_engine", None)
    if eng is None:
        return {"trades": [], "total": 0, "page": page, "page_size": page_size, "pages": 1}
    return eng.performance_trades(
        page=page, page_size=page_size,
        symbol=symbol, date_from=date_from, date_to=date_to,
    )


@router.get("/summary")
async def get_performance_summary(request: Request) -> dict[str, Any]:
    """Aggregate session performance: win rate (with N), R-multiples, drawdown,
    equity curve points, daily P&L, rolling win rates.

    Returns zero-state cleanly when no trades have executed.
    """
    eng = getattr(request.app.state, "demo_engine", None)
    if eng is None:
        return _empty_summary()
    return eng.performance_summary()


@router.get("/scan-stats")
async def get_scan_stats(request: Request) -> dict[str, Any]:
    """Scan rejection breakdown: how many symbols were scanned, passed Tier-A,
    qualified for Tier-B, and which pillar each rejected symbol failed.

    Used by the performance empty-state screen to show discipline evidence
    even when total_trades == 0.
    """
    eng = getattr(request.app.state, "demo_engine", None)
    if eng is None:
        return {
            "symbols_scanned": 0,
            "tier_a_count": 0,
            "tier_b_count": 0,
            "rejected_from_tier_b": [],
        }
    return eng.scan_stats()


def _empty_summary() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate_value": None,
        "win_rate_str": "—",
        "avg_r_winners": None,
        "avg_r_losers": None,
        "max_drawdown_pct": 0.0,
        "give_back_pct_from_peak": 0.0,
        "rule_violation_count": 0,
        "rolling_5_win_rate": None,
        "rolling_20_win_rate": None,
        "equity_curve": [],
        "daily_pnl": [],
        "realized_pnl": "0.00",
        "peak_pnl": "0.00",
        "max_daily_loss_limit": "0.00",
        "give_back_warn_pct": 0.25,
        "give_back_hard_pct": 0.50,
    }
