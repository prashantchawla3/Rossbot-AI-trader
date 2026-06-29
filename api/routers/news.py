"""News router — GET /api/news/{symbol}.

Returns the last 10 cached news items for a symbol plus the live CatalystVerifier
result (VERIFIED / SKIP / UNVERIFIED).  All data is in-memory; no external call
is made during the request — the NewsStreamAdapter pre-populates the cache via
the Alpaca WebSocket feed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.news.catalyst_verifier import CatalystVerifier
from core.news.news_stream import NewsStreamAdapter

router = APIRouter(prefix="/api", tags=["news"])


def _stream(request: Request) -> NewsStreamAdapter | None:
    return getattr(request.app.state, "news_stream", None)


def _verifier(request: Request) -> CatalystVerifier | None:
    return getattr(request.app.state, "catalyst_verifier", None)


@router.get("/news/{symbol}")
async def get_news(symbol: str, request: Request) -> dict[str, Any]:
    """Return recent news and CatalystVerifier verdict for ``symbol``.

    Response shape::

        {
          "symbol": "AAPL",
          "catalyst_result": {"status": "VERIFIED", "type": "contract_win", "reason": "..."},
          "recent_news": [
            {"headline": "...", "created_at": "2026-06-29T14:30:00+00:00", "source": "benzinga"},
            ...
          ]
        }
    """
    sym = symbol.upper()

    stream = _stream(request)
    verifier = _verifier(request)

    # Catalyst verdict (defaults to UNVERIFIED when stream not yet connected)
    if verifier is not None:
        result = await verifier.verify(sym)
        catalyst_result = {
            "status": result.status,
            "type": result.catalyst_type,
            "reason": result.reason,
        }
    else:
        catalyst_result = {
            "status": "UNVERIFIED",
            "type": "none",
            "reason": "news_stream_not_initialized",
        }

    # Recent news (last 10 within 60-minute window)
    if stream is not None:
        items = await stream.get_recent_news(sym, lookback_minutes=60)
        recent_news = [
            {
                "headline": item.headline,
                "created_at": item.created_at.isoformat(),
                "source": item.source,
                "summary": item.summary,
            }
            for item in items[:10]
        ]
    else:
        recent_news = []

    return {
        "symbol": sym,
        "catalyst_result": catalyst_result,
        "recent_news": recent_news,
    }
