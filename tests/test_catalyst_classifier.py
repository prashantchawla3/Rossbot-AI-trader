"""Unit tests for CatalystClassifier (core/news/catalyst_classifier.py).

Covers every SKIP category and every VERIFIED catalyst type with representative
headlines drawn from the Ross Cameron strategy spec (§1 SKIP_1–SKIP_7 / §13.1).

The classifier is a pure function (no I/O, no network) so all tests are
synchronous and run without mocking.
"""

from __future__ import annotations

import pytest

from core.news.catalyst_classifier import CatalystClassifier, CatalystResult

_clf = CatalystClassifier()


def classify(headline: str, summary: str = "") -> CatalystResult:
    return _clf.classify(
        symbol="TSYM",
        headline=headline,
        summary=summary,
        source="benzinga",
    )


# ── SKIP keywords — hard block (U15 / spec §1 SKIP_1–SKIP_7) ─────────────────


class TestSkipKeywords:
    """Every SKIP phrase must produce status=SKIP and never leak VERIFIED."""

    @pytest.mark.parametrize("text,expected_type", [
        # SKIP_1: buyout / acquisition
        ("PTPI agrees to be acquired by BigPharma for $5/share", "buyout_acquisition"),
        ("Company announces buyout of rival firm", "buyout_acquisition"),
        ("Acquisition of ACME Corp by TechGiant confirmed", "buyout_acquisition"),
        ("Firm being acquired in $2B private-equity deal", "buyout_acquisition"),
        ("Merger agreement signed between Apex and Nexus", "buyout_acquisition"),
        ("Tender offer launched for all outstanding shares at $12", "buyout_acquisition"),
        # SKIP_2: secondary / shelf offerings
        ("PALI announces underwritten public offering of 5M shares", "secondary_offering"),
        ("Company files S-3 registration statement for shelf offering", "secondary_offering"),
        ("ACME prices follow-on offering of 3.5M shares at $4.20", "secondary_offering"),
        ("Registered direct offering of 2M shares completed", "secondary_offering"),
        ("Shelf registration filed for future capital raises", "secondary_offering"),
        ("ATM offering program expanded to $50M capacity", "secondary_offering"),
        ("Dilution risk: company raises via direct offering at 20% discount", "secondary_offering"),
        # SKIP_3: pump / newsletter
        ("Newsletter: hot stock alert — this one could 10x!", "pump_newsletter"),
        ("Pump alert: insider-sourced text alert $XXXX", "pump_newsletter"),
        ("Paid promotion: penny stock alert for Tuesday morning", "pump_newsletter"),
        ("Promotional research report distributed by email", "pump_newsletter"),
        # SKIP_4: recycled / reissued news
        ("Recycled press release from March resurfaces today", "recycled_news"),
        ("Company reissued last year's partnership announcement", "recycled_news"),
        ("Previously announced deal reaches closing milestone", "recycled_news"),
        # SKIP_5: five-cent tick pilot
        ("Stock added to five-cent tick pilot program by FINRA", "five_cent_tick"),
        ("SEC expands 5-cent tick pilot to additional symbols", "five_cent_tick"),
        ("Nickel spread pilot enrollment confirmed for symbol", "five_cent_tick"),
    ])
    def test_skip_returned(self, text: str, expected_type: str) -> None:
        result = classify(text)
        assert result.status == "SKIP", (
            f"Expected SKIP for {text!r} but got {result.status!r}"
        )
        assert result.catalyst_type == expected_type, (
            f"Expected type={expected_type!r} but got {result.catalyst_type!r}"
        )

    def test_skip_in_summary_also_blocks(self) -> None:
        """SKIP keywords in the summary (not headline) must still hard-block."""
        result = classify(
            headline="Stock surges 40% on volume",
            summary="Company has filed an S-3 registration statement.",
        )
        assert result.status == "SKIP"

    def test_skip_beats_verified_in_same_text(self) -> None:
        """A text containing both SKIP and VERIFIED phrases must return SKIP."""
        result = classify("FDA approval granted; however secondary offering filed today")
        assert result.status == "SKIP", "SKIP must beat VERIFIED in the same article"

    def test_skip_case_insensitive(self) -> None:
        result = classify("COMPANY TO BE ACQUIRED BY RIVAL")
        assert result.status == "SKIP"


# ── VERIFIED catalyst types ────────────────────────────────────────────────────


class TestVerifiedCatalysts:
    """Each recognised catalyst type returns status=VERIFIED."""

    @pytest.mark.parametrize("text,expected_type", [
        # biotech_fda
        ("FDA approves new drug for rare childhood disease", "biotech_fda"),
        ("Phase 3 clinical trial shows statistically significant results", "biotech_fda"),
        ("PDUFA date set for Q3 — analysts expect approval", "biotech_fda"),
        ("Company submits new drug application for oncology treatment", "biotech_fda"),
        ("BLA filing accepted by FDA for novel biologic", "biotech_fda"),
        ("Trial results show 60% reduction in primary endpoint", "biotech_fda"),
        # earnings_beat
        ("Company reports earnings beat on both EPS and revenue", "earnings_beat"),
        ("Revenue beat consensus by 12% — shares surge pre-market", "earnings_beat"),
        ("EPS above analyst estimates for the second consecutive quarter", "earnings_beat"),
        ("Firm beats expectations; Q2 results released", "earnings_beat"),
        # contract_win
        ("Small-cap wins major contract with US Department of Defense", "contract_win"),
        ("Strategic partnership signed for supply chain expansion", "contract_win"),
        ("Agreement with Nvidia to supply custom AI chips", "contract_win"),
        ("Supply agreement with Amazon Web Services worth $200M", "contract_win"),
        # ai_partnership
        ("AI partnership with leading technology firm announced", "ai_partnership"),
        ("Artificial intelligence integration deal to boost margins", "ai_partnership"),
        # crypto_treasury
        ("Board approves bitcoin treasury reserve strategy", "crypto_treasury"),
        ("Company discloses crypto purchase of 500 BTC", "crypto_treasury"),
        # ipo_or_reverse_split
        ("Company announces reverse split at ratio of 1-for-10", "ipo_or_reverse_split"),
        ("SPAC merger vote approved by shareholders at special meeting", "ipo_or_reverse_split"),
        # activist_investor
        ("Activist investor discloses 13D filing with 11% stake", "activist_investor"),
        ("13G filed: fund discloses significant stake in company", "activist_investor"),
        ("Activist shareholder calls for board restructuring", "activist_investor"),
        ("Major shareholder increases stake to 15%", "activist_investor"),
    ])
    def test_verified_returned(self, text: str, expected_type: str) -> None:
        result = classify(text)
        assert result.status == "VERIFIED", (
            f"Expected VERIFIED for {text!r} but got {result.status!r}"
        )
        assert result.catalyst_type == expected_type, (
            f"Expected type={expected_type!r} but got {result.catalyst_type!r}"
        )

    def test_verified_case_insensitive(self) -> None:
        result = classify("PHASE 3 TRIAL RESULTS MEET PRIMARY ENDPOINT")
        assert result.status == "VERIFIED"
        assert result.catalyst_type == "biotech_fda"

    def test_verified_match_in_summary(self) -> None:
        result = classify(
            headline="Shares move significantly in pre-market",
            summary="The company has received FDA drug approval for its lead asset.",
        )
        assert result.status == "VERIFIED"
        assert result.catalyst_type == "biotech_fda"


# ── UNVERIFIED fallback ────────────────────────────────────────────────────────


class TestUnverified:
    """Headlines with no recognised catalyst phrase return UNVERIFIED."""

    @pytest.mark.parametrize("text", [
        "Stock jumps 45% on heavy volume with no news catalyst",
        "Price action suggests technical breakout above resistance",
        "Short interest increases significantly over past week",
        "Analyst upgrades price target by $2",
        "Quarterly earnings date scheduled for next Tuesday",
    ])
    def test_no_catalyst_unverified(self, text: str) -> None:
        result = classify(text)
        assert result.status == "UNVERIFIED"
        assert result.reason == "no_recognized_catalyst"

    def test_empty_strings_unverified(self) -> None:
        result = classify("", "")
        assert result.status == "UNVERIFIED"


# ── CatalystResult dataclass ───────────────────────────────────────────────────


class TestCatalystResultContract:
    """CatalystResult is a frozen dataclass with the three required fields."""

    def test_fields_present(self) -> None:
        r = CatalystResult(status="VERIFIED", catalyst_type="biotech_fda", reason="x")
        assert r.status == "VERIFIED"
        assert r.catalyst_type == "biotech_fda"
        assert r.reason == "x"

    def test_frozen(self) -> None:
        r = CatalystResult(status="SKIP", catalyst_type="buyout_acquisition", reason="y")
        with pytest.raises(Exception):  # frozen dataclass raises on mutation
            r.status = "VERIFIED"  # type: ignore[misc]

    def test_reason_contains_matched_phrase(self) -> None:
        r = classify("FDA approves drug")
        assert "fda" in r.reason
