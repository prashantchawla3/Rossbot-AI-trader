"""SEC EDGAR submissions check for dilution / stake filings — spec §1 §13.1.

Uses two free EDGAR REST endpoints (no API key required):
  - company_tickers.json   → ticker → CIK lookup
  - submissions/CIK###.json → all recent filings for the company (form + date)

Checks for recent S-1/S-3/424B* filings → SKIP (secondary offering, spec §1 SKIP_3).
Also exposes has_stake_filing() for 13D/13G (accepted catalyst: >10% investor stake).

Endpoint docs verified: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
Rate limit: ~10 req/s (same fair-access policy as adapters/edgar.py).
Network I/O injected via ``fetch`` for offline testability.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from urllib.request import Request, urlopen

from adapters.edgar import parse_ticker_map

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Form types that signal dilution / secondary risk (spec §1 SKIP_3, §13.1)
DILUTION_FORMS: frozenset[str] = frozenset({
    "S-1", "S-3", "S-1/A", "S-3/A",
    "424B1", "424B2", "424B3", "424B4", "424B5",
    "424B1/A", "424B3/A",
})

# Form types for large-holder stake disclosure (accepted catalyst: >10% stake, §1)
STAKE_FORMS: frozenset[str] = frozenset({
    "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A",
})

Fetcher = Callable[[str, str], bytes]


def _urllib_fetch(url: str, user_agent: str) -> bytes:
    req = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    with urlopen(req, timeout=15) as resp:
        return resp.read()


def _has_recent_filing(raw: bytes, forms: frozenset[str], lookback_days: int) -> bool:
    """Return True if any filing in the submissions JSON matches a form type within the window."""
    cutoff = date.today() - timedelta(days=lookback_days)
    try:
        obj = json.loads(raw)
    except Exception:
        return False
    recent = obj.get("filings", {}).get("recent", {})
    form_list: list[str] = recent.get("form", [])
    date_list: list[str] = recent.get("filingDate", [])
    for form, dt_str in zip(form_list, date_list):
        if form.upper() in forms:
            try:
                filing_date = date.fromisoformat(dt_str)
            except ValueError:
                continue
            if filing_date >= cutoff:
                return True
    return False


class SecFilingClient:
    """Checks EDGAR submissions for recent dilution or stake filings for a ticker.

    CIK lookup is cached in-memory after the first call (the tickers file is ~800 KB;
    reloading per-symbol would exceed the EDGAR rate limit in scanner loops).
    """

    def __init__(self, user_agent: str, fetch: Fetcher | None = None) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError("EDGAR User-Agent must include a contact email (SEC fair-access)")
        self.user_agent = user_agent
        self._fetch: Fetcher = fetch or _urllib_fetch
        self._ticker_map: dict[str, str] | None = None

    def _get_cik(self, ticker: str) -> str | None:
        if self._ticker_map is None:
            raw = self._fetch(COMPANY_TICKERS_URL, self.user_agent)
            self._ticker_map = parse_ticker_map(raw)
        return self._ticker_map.get(ticker.upper())

    def _submissions_raw(self, cik: str) -> bytes | None:
        url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
        try:
            return self._fetch(url, self.user_agent)
        except Exception:
            return None  # network failure → caller treats as no filings

    def has_dilution_filing(self, ticker: str, lookback_days: int = 30) -> bool:
        """True if a recent S-1/S-3/424B filing exists → SKIP (secondary/shelf, spec §1 SKIP_3).

        Returns False on any network/parse failure (fail-safe: don't false-SKIP on outage).
        """
        cik = self._get_cik(ticker)
        if cik is None:
            return False  # unknown ticker → no filing data, don't block
        raw = self._submissions_raw(cik)
        if raw is None:
            return False
        return _has_recent_filing(raw, DILUTION_FORMS, lookback_days)

    def has_stake_filing(self, ticker: str, lookback_days: int = 30) -> bool:
        """True if a recent 13D/13G (>10% investor stake) filing exists (accepted catalyst)."""
        cik = self._get_cik(ticker)
        if cik is None:
            return False
        raw = self._submissions_raw(cik)
        if raw is None:
            return False
        return _has_recent_filing(raw, STAKE_FORMS, lookback_days)


__all__ = [
    "DILUTION_FORMS",
    "STAKE_FORMS",
    "SecFilingClient",
]
