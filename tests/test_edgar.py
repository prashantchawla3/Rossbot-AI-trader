"""EDGAR client tests — offline, via an injected fetcher (no network)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from adapters.edgar import (
    COMPANY_TICKERS_URL,
    EdgarClient,
    pad_cik,
    parse_latest_shares,
    parse_ticker_map,
)
from core.scanner.float_resolver import FloatConfidence, resolve_float

_TICKERS = json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}).encode()
_CONCEPT = json.dumps(
    {
        "units": {
            "shares": [
                {"end": "2025-12-31", "val": 1000, "form": "10-K"},
                {"end": "2026-03-31", "val": 1200, "form": "10-Q"},  # most recent
            ]
        }
    }
).encode()


def test_pad_cik() -> None:
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("CIK320193") == "0000320193"
    with pytest.raises(ValueError, match="invalid CIK"):
        pad_cik("abc")


def test_parse_ticker_map() -> None:
    assert parse_ticker_map(_TICKERS) == {"AAPL": "0000320193"}


def test_parse_latest_shares_picks_most_recent() -> None:
    parsed = parse_latest_shares(_CONCEPT)
    assert parsed == (1200, date(2026, 3, 31))


def test_parse_latest_shares_empty() -> None:
    assert parse_latest_shares(json.dumps({"units": {}}).encode()) is None


def test_client_resolves_shares_outstanding() -> None:
    def fake_fetch(url: str, user_agent: str) -> bytes:
        assert "@" in user_agent  # SEC fair-access UA enforced
        return _TICKERS if url == COMPANY_TICKERS_URL else _CONCEPT

    client = EdgarClient("RossBot test (ops@example.com)", fetch=fake_fetch)
    cand = client.shares_outstanding("AAPL")
    assert cand.shares == 1200
    assert cand.is_free_float is False
    assert cand.source == "sec_edgar"

    # Plugs into the resolver as a shares-outstanding proxy (MEDIUM confidence).
    res = resolve_float([cand])
    assert res.confidence is FloatConfidence.MEDIUM


def test_client_unknown_ticker_returns_empty_candidate() -> None:
    client = EdgarClient("RossBot test (ops@example.com)", fetch=lambda url, ua: _TICKERS)
    cand = client.shares_outstanding("ZZZZ")
    assert cand.shares is None


def test_client_rejects_bad_user_agent() -> None:
    with pytest.raises(ValueError, match="contact email"):
        EdgarClient("no-email-here")
