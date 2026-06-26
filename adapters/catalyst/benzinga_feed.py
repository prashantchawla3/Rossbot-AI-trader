"""Benzinga Pro REST news feed client — spec §1 NEWS_SOURCES / §13.1.

REST endpoint: https://api.benzinga.com/api/v2/news
WebSocket stream: wss://api.benzinga.com/api/v1/news/stream (Phase 8+ if needed)
Docs: https://docs.benzinga.com/home (verified 2026-06-26)

Authentication: BENZINGA_API_KEY env var (never store in DB or config table — secrets).
Ticker filter: ``tickers`` query param.
Time filter: ``updatedSince`` Unix epoch seconds (delta polling for minimal latency).

Returns empty list on any error → NLPCatalystProvider returns UNVERIFIED (fail-safe).
Network I/O injected via ``fetch`` for offline testability.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from adapters.catalyst.models import NewsItem

BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"
_DEFAULT_LOOKBACK_SECONDS = 3 * 3600  # 3-hour window covers pre-market + first hour

# fetch(url, headers_dict) → raw bytes
Fetcher = Callable[[str, dict[str, str]], bytes]


def _urllib_fetch(url: str, headers: dict[str, str]) -> bytes:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=10) as resp:
        return resp.read()


def _parse_items(raw: bytes, max_items: int) -> list[NewsItem]:
    """Parse Benzinga REST JSON array → NewsItem list. Tolerates unexpected shapes."""
    try:
        items = json.loads(raw)
    except Exception:
        return []
    if not isinstance(items, list):
        # Some response shapes wrap in {"result": [...]}
        if isinstance(items, dict):
            items = items.get("result", items.get("news", []))
    if not isinstance(items, list):
        return []
    result: list[NewsItem] = []
    for item in items[:max_items]:
        headline = item.get("title") or item.get("headline") or ""
        if not headline:
            continue
        result.append(NewsItem(
            headline=headline,
            body=item.get("body", ""),
            url=item.get("url", ""),
            source=item.get("source", "benzinga"),
            published_at=item.get("updated", "") or item.get("created", ""),
        ))
    return result


class BenzingaNewsClient:
    """Fetches recent headlines for a ticker from Benzinga Pro REST API.

    Falls back to empty list on any error (missing key, network failure, parse error).
    """

    def __init__(
        self,
        api_key: str | None = None,
        fetch: Fetcher | None = None,
        lookback_seconds: int = _DEFAULT_LOOKBACK_SECONDS,
    ) -> None:
        self._api_key = api_key or os.environ.get("BENZINGA_API_KEY", "")
        self._fetch: Fetcher = fetch or _urllib_fetch
        self._lookback_seconds = lookback_seconds

    def _has_key(self) -> bool:
        return bool(self._api_key)

    def get_headlines(self, symbol: str, max_items: int = 5) -> list[NewsItem]:
        """Return recent headlines for ``symbol``. Empty list on any error or missing key."""
        if not self._has_key():
            return []
        params: dict[str, str] = {
            "token": self._api_key,
            "tickers": symbol.upper(),
            "updatedSince": str(int(time.time()) - self._lookback_seconds),
            "pageSize": str(max(1, max_items)),
            "displayOutput": "abstract",  # headline + teaser without full body (cost control)
        }
        url = f"{BENZINGA_NEWS_URL}?{urlencode(params)}"
        try:
            raw = self._fetch(url, {"Accept": "application/json"})
            return _parse_items(raw, max_items)
        except Exception:
            return []


__all__ = ["BenzingaNewsClient", "NewsItem"]
