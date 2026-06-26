"""Tests for the keyword SKIP filter (adapters/catalyst/keyword_filter.py)."""

from __future__ import annotations

import pytest

from adapters.catalyst.keyword_filter import KeywordHit, scan_for_skip
from adapters.catalyst.models import CatalystTag


# ---- SKIP hits ----

@pytest.mark.parametrize("text,expected_tag", [
    # §1 SKIP_1 buyout / acquisition
    ("PTPI agrees to be acquired by BigPharma Inc. for $5 per share", CatalystTag.BUYOUT_SKIP),
    ("Company announces buyout agreement with private equity firm", CatalystTag.BUYOUT_SKIP),
    ("Tender offer launched for all outstanding shares at $12", CatalystTag.BUYOUT_SKIP),
    ("Firm will be acquired in $2B deal announced today", CatalystTag.BUYOUT_SKIP),
    # §1 SKIP_3 secondary / shelf offering
    ("PALI announces underwritten public offering of 5 million shares", CatalystTag.SECONDARY_OFFERING_SKIP),
    ("Company files S-3 registration statement for shelf offering", CatalystTag.SECONDARY_OFFERING_SKIP),
    ("ACME prices follow-on offering of 3.5 million shares", CatalystTag.SECONDARY_OFFERING_SKIP),
    ("Registered direct offering completed at $4.50 per share", CatalystTag.SECONDARY_OFFERING_SKIP),
    ("Company prices 2 million shares at $8.50 per share", CatalystTag.SECONDARY_OFFERING_SKIP),
    # §1 SKIP_4 pump
    ("Stock promotion newsletter alert — hot pick for Tuesday", CatalystTag.PUMP_SKIP),
    ("Paid promotion: penny stock alert $XXXX gains expected", CatalystTag.PUMP_SKIP),
    # §1 SKIP_6 five-cent tick
    ("Stock added to five cent tick pilot program by FINRA", CatalystTag.FIVE_CENT_TICK_SKIP),
])
def test_scan_returns_skip(text: str, expected_tag: CatalystTag) -> None:
    hit = scan_for_skip(text)
    assert hit is not None, f"Expected a SKIP hit for: {text!r}"
    assert isinstance(hit, KeywordHit)
    assert hit.tag is expected_tag


# ---- No SKIP match (accepted or neutral catalysts) ----

@pytest.mark.parametrize("text", [
    "FDA approves PALI drug for rare disease indication",
    "Company reports Q4 earnings beat, revenue up 30%",
    "Major contract win with Nvidia for AI chip supply",
    "Biotech announces positive Phase 3 clinical trial topline results",
    "Company launches bitcoin treasury acquisition strategy",
    "Recent reverse stock split effective today",
    "SPAC merger vote approved by shareholders",
    "Stock jumps 45% on heavy volume with no news catalyst",
    "13G filing: Investor discloses 11% stake in the company",
])
def test_scan_returns_none_for_good_catalysts(text: str) -> None:
    assert scan_for_skip(text) is None, f"Unexpected SKIP hit for: {text!r}"


def test_case_insensitive() -> None:
    """Keyword scan is case-insensitive."""
    assert scan_for_skip("PTPI AGREES TO BE ACQUIRED") is not None
    assert scan_for_skip("Secondary Offering Of 2 Million Shares") is not None


def test_returns_first_match() -> None:
    """Returns the first matching phrase (deterministic)."""
    text = "buyout agreement for secondary offering"
    hit = scan_for_skip(text)
    assert hit is not None
    assert hit.tag is CatalystTag.BUYOUT_SKIP  # buyout rule is checked first
