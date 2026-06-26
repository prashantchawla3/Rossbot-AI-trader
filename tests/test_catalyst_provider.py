"""Acceptance tests for NLPCatalystProvider (adapters/catalyst/provider.py).

All sub-components are injected with offline stubs — no real network calls.
Acceptance criteria (spec §13.1):
  - PALI (secondary offering) → SKIP
  - PTPI (buyout) → SKIP
  - Clean FDA catalyst → VERIFIED (with reaction proof passing)
  - Ambiguity / low confidence → UNVERIFIED (safe side)
  - Provider no longer fails closed by default but still skips on low confidence
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest

from adapters.catalyst.benzinga_feed import BenzingaNewsClient
from adapters.catalyst.llm_classifier import LLMCatalystClassifier
from adapters.catalyst.models import CatalystTag, NewsItem
from adapters.catalyst.provider import NLPCatalystProvider
from adapters.catalyst.sec_filing import SecFilingClient
from adapters.providers import CatalystVerdict


# ---- Offline sub-component stubs ----

def _make_news_client(headlines: list[str]) -> BenzingaNewsClient:
    """BenzingaNewsClient that returns fixed headlines (no network call)."""
    items = [NewsItem(headline=h) for h in headlines]

    def _fake_fetch(url: str, headers: dict) -> bytes:
        return json.dumps([{"title": h} for h in headlines]).encode()

    return BenzingaNewsClient(api_key="fake", fetch=_fake_fetch)


def _make_empty_news_client() -> BenzingaNewsClient:
    """BenzingaNewsClient with no API key → always returns []."""
    return BenzingaNewsClient(api_key="")


def _make_sec_client(has_dilution: bool = False) -> SecFilingClient:
    today = date.today().isoformat()
    form = "S-3" if has_dilution else "8-K"
    # Build a tickers map that covers all symbols used in these tests.
    _test_tickers = ["PALI", "PTPI", "AMAM", "EARN", "AMBI", "UNKN", "SMBL", "CACH"]
    _tickers_json = json.dumps(
        {str(i): {"cik_str": i + 1, "ticker": t, "title": t} for i, t in enumerate(_test_tickers)}
    ).encode()

    def _fetch(url: str, _ua: str) -> bytes:
        if "company_tickers" in url:
            return _tickers_json
        return json.dumps({
            "filings": {"recent": {"form": [form], "filingDate": [today]}}
        }).encode()

    return SecFilingClient(user_agent="test test@example.com", fetch=_fetch)


def _make_llm_classifier(tag: str, confidence: float) -> LLMCatalystClassifier:
    payload = json.dumps({"tag": tag, "confidence": confidence, "reasoning": "test"})

    class _C:
        text = payload

    class _R:
        content = [_C()]

    class _M:
        def create(self, **_: object) -> _R:
            return _R()

    class _Client:
        messages = _M()

    return LLMCatalystClassifier(api_key="fake", client=_Client())


def _provider(
    headlines: list[str],
    llm_tag: str = "unknown",
    llm_conf: float = 0.30,
    has_dilution: bool = False,
    confidence_threshold: Decimal = Decimal("0.70"),
    llm_enabled: bool = True,
) -> NLPCatalystProvider:
    return NLPCatalystProvider(
        news_client=_make_news_client(headlines) if headlines else _make_empty_news_client(),
        sec_client=_make_sec_client(has_dilution),
        llm_classifier=_make_llm_classifier(llm_tag, llm_conf),
        confidence_threshold=confidence_threshold,
        llm_enabled=llm_enabled,
    )


# ---- PALI (secondary offering) ----

def test_pali_sec_dilution_filing_returns_skip() -> None:
    """PALI: SEC has a recent S-3 filing → SKIP before even fetching headlines."""
    p = _provider(headlines=[], has_dilution=True)
    result = asyncio.run(p.classify("PALI"))
    assert result is CatalystVerdict.SKIP


def test_pali_headline_keyword_returns_skip() -> None:
    """PALI: secondary offering keyword in headline → SKIP."""
    p = _provider(
        headlines=["PALI prices underwritten public offering of 10 million shares at $3.00"],
        has_dilution=False,
    )
    result = asyncio.run(p.classify("PALI"))
    assert result is CatalystVerdict.SKIP


def test_pali_llm_secondary_skip() -> None:
    """PALI: LLM classifies secondary_offering_skip → SKIP."""
    p = _provider(
        headlines=["PALI announces new share offering to fund operations"],
        llm_tag="secondary_offering_skip",
        llm_conf=0.95,
        has_dilution=False,
    )
    result = asyncio.run(p.classify("PALI"))
    assert result is CatalystVerdict.SKIP


# ---- PTPI (buyout) ----

def test_ptpi_keyword_buyout_returns_skip() -> None:
    """PTPI: buyout keyword in headline → SKIP."""
    p = _provider(
        headlines=["PTPI agrees to be acquired by Pharma Giant for $5 per share"],
        has_dilution=False,
    )
    result = asyncio.run(p.classify("PTPI"))
    assert result is CatalystVerdict.SKIP


def test_ptpi_llm_buyout_skip() -> None:
    """PTPI: LLM classifies buyout_skip → SKIP."""
    p = _provider(
        headlines=["Major acquisition agreement announced for PTPI"],
        llm_tag="buyout_skip",
        llm_conf=0.98,
        has_dilution=False,
    )
    result = asyncio.run(p.classify("PTPI"))
    assert result is CatalystVerdict.SKIP


# ---- Clean FDA catalyst → VERIFIED ----

def test_fda_clean_headline_returns_verified() -> None:
    """FDA approval headline + LLM high-confidence → VERIFIED."""
    p = _provider(
        headlines=["FDA grants accelerated approval for AMAM's rare disease drug"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.96,
        has_dilution=False,
    )
    result = asyncio.run(p.classify("AMAM"))
    assert result is CatalystVerdict.VERIFIED


def test_fda_verified_with_reaction_proof() -> None:
    """FDA catalyst + rvol=10×, roc=30% → VERIFIED (reaction proof passes)."""
    p = _provider(
        headlines=["FDA approves drug — pivotal trial results exceed expectations"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.95,
        has_dilution=False,
    )
    result = asyncio.run(p.classify("AMAM", rvol=Decimal("10"), roc_pct=Decimal("30")))
    assert result is CatalystVerdict.VERIFIED


def test_earnings_beat_returns_verified() -> None:
    p = _provider(
        headlines=["Company reports massive Q4 earnings beat, revenue up 60%"],
        llm_tag="earnings_beat",
        llm_conf=0.92,
    )
    result = asyncio.run(p.classify("EARN"))
    assert result is CatalystVerdict.VERIFIED


# ---- Ambiguity → UNVERIFIED ----

def test_no_headlines_returns_unverified() -> None:
    """No Benzinga API key / no headlines → UNVERIFIED (fail-safe)."""
    p = _provider(headlines=[])
    result = asyncio.run(p.classify("UNKN"))
    assert result is CatalystVerdict.UNVERIFIED


def test_llm_low_confidence_returns_unverified() -> None:
    """LLM returns accepted tag but confidence below threshold → UNVERIFIED."""
    p = _provider(
        headlines=["Company may have FDA-related announcement coming"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.50,  # below 0.70 threshold
        confidence_threshold=Decimal("0.70"),
    )
    result = asyncio.run(p.classify("AMBI"))
    assert result is CatalystVerdict.UNVERIFIED


def test_llm_unknown_tag_returns_unverified() -> None:
    p = _provider(
        headlines=["Stock moves higher with no clear catalyst identified"],
        llm_tag="unknown",
        llm_conf=0.30,
    )
    result = asyncio.run(p.classify("UNKN"))
    assert result is CatalystVerdict.UNVERIFIED


def test_llm_disabled_returns_unverified() -> None:
    """LLM disabled (cost control) → UNVERIFIED even with good headlines."""
    p = _provider(
        headlines=["FDA approves drug"],
        llm_enabled=False,
    )
    result = asyncio.run(p.classify("AMAM"))
    assert result is CatalystVerdict.UNVERIFIED


# ---- Reaction-proof gate ----

def test_reaction_gate_low_rvol_returns_unverified() -> None:
    """rvol below 5× → UNVERIFIED before any other check (spec §13.1)."""
    p = _provider(
        headlines=["FDA approves drug"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.99,
    )
    result = asyncio.run(p.classify("AMAM", rvol=Decimal("3"), roc_pct=Decimal("20")))
    assert result is CatalystVerdict.UNVERIFIED


def test_reaction_gate_low_roc_returns_unverified() -> None:
    """roc_pct below 10% → UNVERIFIED (spec §13.1 reaction proof)."""
    p = _provider(
        headlines=["FDA approves drug"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.99,
    )
    result = asyncio.run(p.classify("AMAM", rvol=Decimal("15"), roc_pct=Decimal("5")))
    assert result is CatalystVerdict.UNVERIFIED


def test_reaction_gate_not_applied_when_none() -> None:
    """No rvol/roc_pct passed → reaction gate skipped (trusts scanner already checked)."""
    p = _provider(
        headlines=["FDA approves drug"],
        llm_tag="biotech_clinical_or_fda",
        llm_conf=0.95,
    )
    result = asyncio.run(p.classify("AMAM"))  # no rvol/roc_pct passed
    assert result is CatalystVerdict.VERIFIED


# ---- Regression: stubs still fail closed ----

def test_stub_provider_still_fails_closed() -> None:
    """Ensure the StubCatalystProvider still returns UNVERIFIED (Rule C)."""
    from adapters.stubs import StubCatalystProvider
    stub = StubCatalystProvider()
    result = asyncio.run(stub.classify("AAPL"))
    assert result is CatalystVerdict.UNVERIFIED


def test_stub_accepts_new_kwargs() -> None:
    """Stub accepts rvol/roc_pct kwargs without error (backward-compatible interface)."""
    from adapters.stubs import StubCatalystProvider
    stub = StubCatalystProvider()
    result = asyncio.run(stub.classify("AAPL", rvol=Decimal("10"), roc_pct=Decimal("20")))
    assert result is CatalystVerdict.UNVERIFIED
