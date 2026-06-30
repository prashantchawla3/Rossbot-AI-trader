"""SEC EDGAR share-count client (spec §1 FILINGS_DILUTION; Pillar-2 cross-source).

EDGAR gives **shares outstanding, NOT free float** — a conservative upper bound used to
cross-validate vendor free-float numbers (see ``core.scanner.float_resolver``).

verified: www.sec.gov/search-filings/edgar-application-programming-interfaces (2026-06)
- Company Concept: https://data.sec.gov/api/xbrl/companyconcept/CIK##########/{taxonomy}/{concept}.json
- Shares-outstanding concept: dei:EntityCommonStockSharesOutstanding (cover-page count)
- Ticker→CIK map: https://www.sec.gov/files/company_tickers.json (CIK stored WITHOUT leading
  zeros — pad to 10 digits)
- A descriptive User-Agent header is MANDATORY; rate limit ~10 requests/second.

Network I/O is injected (``fetch``) so the parsing/CIK logic is unit-testable offline.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from urllib.request import Request, urlopen

from core.scanner.float_resolver import FloatCandidate

SEC_SHARES_CONCEPT = "EntityCommonStockSharesOutstanding"
SEC_SHARES_TAXONOMY = "dei"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
RATE_LIMIT_PER_SEC = 10  # SEC fair-access limit; the caller must throttle to this

# fetch(url, user_agent) -> raw JSON bytes.
Fetcher = Callable[[str, str], bytes]


def _urllib_fetch(url: str, user_agent: str) -> bytes:
    # verified: SEC requires a descriptive UA (company + contact email); blank UA is blocked.
    # Accept-Encoding: identity — SEC returns gzip when asked but urllib.request does NOT
    # auto-decompress (unlike the `requests` library); requesting identity avoids needing
    # to call gzip.decompress() on the raw bytes in every caller.
    req = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    with urlopen(req, timeout=15) as resp:
        data: bytes = resp.read()
    return data


def pad_cik(cik: int | str) -> str:
    """Zero-pad a CIK to the 10-digit form EDGAR's concept URLs require."""
    digits = str(cik).lstrip("CIK").strip()
    if not digits.isdigit():
        raise ValueError(f"invalid CIK: {cik!r}")
    return digits.zfill(10)


def parse_ticker_map(raw: bytes) -> dict[str, str]:
    """Parse company_tickers.json → {TICKER: 10-digit CIK}."""
    obj = json.loads(raw)
    # Shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    out: dict[str, str] = {}
    for row in obj.values():
        ticker = str(row["ticker"]).upper()
        out[ticker] = pad_cik(row["cik_str"])
    return out


def parse_latest_shares(raw: bytes) -> tuple[int, date] | None:
    """From a companyconcept JSON, return (shares, as_of) for the most recent data point.

    Picks the fact with the latest ``end`` date across the ``shares`` unit series.
    """
    obj = json.loads(raw)
    units = obj.get("units", {})
    facts = units.get("shares") or units.get("Shares")
    if not facts:
        return None
    best: tuple[int, date] | None = None
    for f in facts:
        val = f.get("val")
        end = f.get("end")
        if val is None or end is None:
            continue
        end_date = date.fromisoformat(end)
        if best is None or end_date > best[1]:
            best = (int(val), end_date)
    return best


class EdgarClient:
    """Resolves a ticker to its latest reported shares outstanding via EDGAR."""

    def __init__(self, user_agent: str, fetch: Fetcher | None = None) -> None:
        if not user_agent or "@" not in user_agent:
            # SEC requires a descriptive UA incl. a contact email; refuse to send a bad one.
            raise ValueError("EDGAR User-Agent must include a contact email (SEC fair-access)")
        self.user_agent = user_agent
        self._fetch: Fetcher = fetch or _urllib_fetch
        self._ticker_map: dict[str, str] | None = None

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_map is None:
            self._ticker_map = parse_ticker_map(self._fetch(COMPANY_TICKERS_URL, self.user_agent))
        return self._ticker_map

    def ticker_to_cik(self, ticker: str) -> str | None:
        return self._load_ticker_map().get(ticker.upper())

    def shares_outstanding(self, ticker: str) -> FloatCandidate:
        """Return a shares-outstanding ``FloatCandidate`` (``is_free_float=False``).

        On any miss (unknown ticker, no data) returns a candidate with ``shares=None`` so the
        resolver treats it as a non-source rather than failing the whole resolution.
        """
        cik = self.ticker_to_cik(ticker)
        if cik is None:
            return FloatCandidate(source="sec_edgar", shares=None, is_free_float=False)
        url = (
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/"
            f"{SEC_SHARES_TAXONOMY}/{SEC_SHARES_CONCEPT}.json"
        )
        parsed = parse_latest_shares(self._fetch(url, self.user_agent))
        if parsed is None:
            return FloatCandidate(source="sec_edgar", shares=None, is_free_float=False)
        shares, as_of = parsed
        return FloatCandidate(source="sec_edgar", shares=shares, is_free_float=False, as_of=as_of)


__all__ = [
    "COMPANY_TICKERS_URL",
    "RATE_LIMIT_PER_SEC",
    "SEC_SHARES_CONCEPT",
    "EdgarClient",
    "pad_cik",
    "parse_latest_shares",
    "parse_ticker_map",
]
