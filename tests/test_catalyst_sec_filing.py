"""Tests for SecFilingClient (adapters/catalyst/sec_filing.py). All offline via injected fetch."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from adapters.catalyst.sec_filing import SecFilingClient, _has_recent_filing, DILUTION_FORMS


# ---- helpers ----

def _make_submissions_bytes(forms: list[str], dates: list[str]) -> bytes:
    return json.dumps({
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": dates,
            }
        }
    }).encode()


def _make_tickers_bytes(ticker: str, cik: int = 12345) -> bytes:
    return json.dumps({"0": {"cik_str": cik, "ticker": ticker, "title": "TEST CO"}}).encode()


def _build_mock_fetch(ticker: str, submissions_bytes: bytes, cik: int = 12345):
    tickers_bytes = _make_tickers_bytes(ticker, cik)
    def _fetch(url: str, _ua: str) -> bytes:
        if "company_tickers" in url:
            return tickers_bytes
        if "submissions" in url:
            return submissions_bytes
        return b"{}"
    return _fetch


# ---- _has_recent_filing unit tests ----

def test_has_recent_filing_detects_s3() -> None:
    today = date.today().isoformat()
    raw = _make_submissions_bytes(["S-3", "8-K"], [today, today])
    assert _has_recent_filing(raw, DILUTION_FORMS, lookback_days=30) is True


def test_has_recent_filing_detects_424b3() -> None:
    today = date.today().isoformat()
    raw = _make_submissions_bytes(["424B3"], [today])
    assert _has_recent_filing(raw, DILUTION_FORMS, lookback_days=30) is True


def test_has_recent_filing_old_filing_excluded() -> None:
    old_date = (date.today() - timedelta(days=60)).isoformat()
    raw = _make_submissions_bytes(["S-3"], [old_date])
    assert _has_recent_filing(raw, DILUTION_FORMS, lookback_days=30) is False


def test_has_recent_filing_8k_not_dilution() -> None:
    today = date.today().isoformat()
    raw = _make_submissions_bytes(["8-K", "10-Q"], [today, today])
    assert _has_recent_filing(raw, DILUTION_FORMS, lookback_days=30) is False


def test_has_recent_filing_empty() -> None:
    raw = _make_submissions_bytes([], [])
    assert _has_recent_filing(raw, DILUTION_FORMS, lookback_days=30) is False


def test_has_recent_filing_bad_json() -> None:
    assert _has_recent_filing(b"NOT JSON", DILUTION_FORMS, lookback_days=30) is False


# ---- SecFilingClient integration tests (offline) ----

def test_pali_secondary_offering_detected() -> None:
    """PALI: S-3 filing today → has_dilution_filing returns True → SKIP (spec §1 SKIP_3)."""
    today = date.today().isoformat()
    subs = _make_submissions_bytes(["S-3", "8-K"], [today, today])
    client = SecFilingClient(
        user_agent="test test@example.com",
        fetch=_build_mock_fetch("PALI", subs),
    )
    assert client.has_dilution_filing("PALI", lookback_days=30) is True


def test_no_dilution_filing() -> None:
    """No dilutive filings → False (no false SKIP)."""
    today = date.today().isoformat()
    subs = _make_submissions_bytes(["8-K", "10-Q", "DEF 14A"], [today, today, today])
    client = SecFilingClient(
        user_agent="test test@example.com",
        fetch=_build_mock_fetch("AAAA", subs),
    )
    assert client.has_dilution_filing("AAAA", lookback_days=30) is False


def test_unknown_ticker_returns_false() -> None:
    """Unknown ticker → CIK lookup misses → False (no false SKIP)."""
    def _fetch(url: str, _ua: str) -> bytes:
        if "company_tickers" in url:
            return json.dumps({"0": {"cik_str": 99, "ticker": "OTHER", "title": "OTHER"}}).encode()
        return b"{}"
    client = SecFilingClient(user_agent="test test@example.com", fetch=_fetch)
    assert client.has_dilution_filing("UNKN", lookback_days=30) is False


def test_network_error_returns_false() -> None:
    """Network failure on submissions fetch → fail-safe False (no false SKIP)."""
    def _fetch(url: str, _ua: str) -> bytes:
        if "company_tickers" in url:
            return _make_tickers_bytes("ERRR")
        raise OSError("simulated network error")
    client = SecFilingClient(user_agent="test test@example.com", fetch=_fetch)
    assert client.has_dilution_filing("ERRR", lookback_days=30) is False


def test_stake_filing_detected() -> None:
    """13D filing today → has_stake_filing returns True."""
    today = date.today().isoformat()
    subs = _make_submissions_bytes(["SC 13D", "8-K"], [today, today])
    client = SecFilingClient(
        user_agent="test test@example.com",
        fetch=_build_mock_fetch("STKE", subs),
    )
    assert client.has_stake_filing("STKE", lookback_days=30) is True


def test_requires_contact_email_in_user_agent() -> None:
    with pytest.raises(ValueError, match="contact email"):
        SecFilingClient(user_agent="RossBot no-email")


def test_ticker_map_cached_across_calls() -> None:
    """CIK ticker map is loaded once and cached (not re-fetched per symbol)."""
    call_count = [0]
    today = date.today().isoformat()
    subs = _make_submissions_bytes(["S-1"], [today])

    def _fetch(url: str, _ua: str) -> bytes:
        if "company_tickers" in url:
            call_count[0] += 1
            return _make_tickers_bytes("CACH")
        return subs

    client = SecFilingClient(user_agent="test test@example.com", fetch=_fetch)
    client.has_dilution_filing("CACH", lookback_days=30)
    client.has_dilution_filing("CACH", lookback_days=30)
    assert call_count[0] == 1  # fetched once, cached on second call
