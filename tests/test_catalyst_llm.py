"""Tests for LLMCatalystClassifier (adapters/catalyst/llm_classifier.py). All offline."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from adapters.catalyst.llm_classifier import LLMCatalystClassifier
from adapters.catalyst.models import CatalystTag, NewsItem


# ---- Fake Anthropic client ----

def _make_fake_client(tag: str, confidence: float, reasoning: str = "test") -> object:
    """Returns a minimal fake object mimicking anthropic.Anthropic.messages.create."""
    payload = json.dumps({"tag": tag, "confidence": confidence, "reasoning": reasoning})

    class _Content:
        text = payload

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **_kwargs: object) -> _Response:
            return _Response()

    class _FakeClient:
        messages = _Messages()

    return _FakeClient()


def _news(headline: str) -> list[NewsItem]:
    return [NewsItem(headline=headline)]


# ---- Acceptance: SKIP classifications ----

def test_ptpi_buyout_classified_skip() -> None:
    """PTPI: buyout headline → LLM returns buyout_skip tag."""
    client = _make_fake_client("buyout_skip", 0.97, "Company is being acquired")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("PTPI", _news("PTPI agrees to be acquired by Pharma Giant Inc."))
    assert result.tag is CatalystTag.BUYOUT_SKIP
    assert result.confidence >= Decimal("0.90")


def test_pali_secondary_classified_skip() -> None:
    """PALI: secondary offering headline → LLM returns secondary_offering_skip."""
    client = _make_fake_client("secondary_offering_skip", 0.99, "Dilutive public offering")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("PALI", _news("PALI prices secondary offering of 10M shares"))
    assert result.tag is CatalystTag.SECONDARY_OFFERING_SKIP


def test_recycled_pr_classified_skip() -> None:
    client = _make_fake_client("recycled_pr_skip", 0.85, "Reissued old press release")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("XXXX", _news("Company republishes 2024 contract announcement"))
    assert result.tag is CatalystTag.RECYCLED_PR_SKIP


# ---- Acceptance: VERIFIED classifications ----

def test_fda_catalyst_verified() -> None:
    """Clean FDA approval headline → biotech_clinical_or_fda at 0.95 confidence."""
    client = _make_fake_client("biotech_clinical_or_fda", 0.95, "FDA approves drug")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("AMAM", _news("FDA grants accelerated approval for AMAM's rare disease drug"))
    assert result.tag is CatalystTag.BIOTECH_FDA
    assert result.confidence >= Decimal("0.95")


def test_earnings_beat_verified() -> None:
    client = _make_fake_client("earnings_beat", 0.90, "Strong earnings beat")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("XYZ", _news("XYZ Corp beats Q3 EPS estimates by 40%"))
    assert result.tag is CatalystTag.EARNINGS_BEAT


# ---- Ambiguity / low confidence → UNKNOWN ----

def test_low_confidence_returns_unknown() -> None:
    """LLM returns a tag but with low confidence → confidence preserved; caller maps to UNVERIFIED."""
    client = _make_fake_client("biotech_clinical_or_fda", 0.45, "Uncertain biotech news")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("ZZZZ", _news("Possible FDA-related announcement from ZZZZ"))
    assert result.tag is CatalystTag.BIOTECH_FDA
    assert result.confidence == Decimal("0.45")  # classifier preserves; provider gates on threshold


def test_ambiguous_headline_returns_unknown() -> None:
    """LLM returns unknown for ambiguous news."""
    client = _make_fake_client("unknown", 0.30, "Cannot determine")
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("AAAA", _news("Stock moves higher on undisclosed news"))
    assert result.tag is CatalystTag.UNKNOWN


# ---- Error paths ----

def test_no_api_key_returns_unknown() -> None:
    clf = LLMCatalystClassifier(api_key="", client=None)
    result = clf.classify("XYZ", _news("Big FDA news"))
    assert result.tag is CatalystTag.UNKNOWN
    assert result.confidence == Decimal("0")


def test_no_headlines_returns_unknown() -> None:
    client = _make_fake_client("biotech_clinical_or_fda", 0.95)
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("XYZ", [])
    assert result.tag is CatalystTag.UNKNOWN


def test_api_error_returns_unknown() -> None:
    class _ErrorMessages:
        def create(self, **_kwargs: object) -> object:
            raise RuntimeError("API call failed")

    class _ErrorClient:
        messages = _ErrorMessages()

    clf = LLMCatalystClassifier(api_key="fake", client=_ErrorClient())
    result = clf.classify("XYZ", _news("Big news"))
    assert result.tag is CatalystTag.UNKNOWN
    assert result.source == "llm_error"


def test_malformed_json_returns_unknown() -> None:
    class _BadContent:
        text = "this is NOT json at all"

    class _BadResponse:
        content = [_BadContent()]

    class _BadMessages:
        def create(self, **_kwargs: object) -> _BadResponse:
            return _BadResponse()

    class _BadClient:
        messages = _BadMessages()

    clf = LLMCatalystClassifier(api_key="fake", client=_BadClient())
    result = clf.classify("XYZ", _news("Big news"))
    assert result.tag is CatalystTag.UNKNOWN


def test_unknown_tag_string_maps_to_unknown() -> None:
    """LLM returns an unrecognised tag string → maps to UNKNOWN."""
    client = _make_fake_client("completely_made_up_tag", 0.99)
    clf = LLMCatalystClassifier(api_key="fake", client=client)
    result = clf.classify("XYZ", _news("News"))
    assert result.tag is CatalystTag.UNKNOWN


def test_markdown_fenced_json_parsed() -> None:
    """LLM wraps response in markdown fences — should still parse correctly."""
    payload = "\n".join([
        "```json",
        json.dumps({"tag": "earnings_beat", "confidence": 0.88, "reasoning": "EPS beat"}),
        "```",
    ])

    class _FencedContent:
        text = payload

    class _FencedResponse:
        content = [_FencedContent()]

    class _FencedMessages:
        def create(self, **_kwargs: object) -> _FencedResponse:
            return _FencedResponse()

    class _FencedClient:
        messages = _FencedMessages()

    clf = LLMCatalystClassifier(api_key="fake", client=_FencedClient())
    result = clf.classify("XYZ", _news("Earnings beat"))
    assert result.tag is CatalystTag.EARNINGS_BEAT
