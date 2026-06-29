"""Keyword-based catalyst classifier — no external API calls, runs in O(n) time.

Two-phase scan (in order):
  1. SKIP check  — any hard-block phrase present → return SKIP immediately.
  2. VERIFIED check — first matching accepted-catalyst phrase → return VERIFIED.
  3. Fallback → UNVERIFIED(reason="no_recognized_catalyst").

SKIP always beats VERIFIED: a headline that contains both "secondary offering" and
"FDA approval" (malformed or aggregated article) is conservatively blocked (U15).

Designed to be called from CatalystVerifier which passes news from the live stream.
All logic is pure (no I/O), fully unit-testable without mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CatalystResult:
    """Classification outcome for a single news item or symbol."""

    status: Literal["VERIFIED", "SKIP", "UNVERIFIED"]
    catalyst_type: str   # e.g. "biotech_fda", "buyout_acquisition", "none"
    reason: str          # e.g. "keyword_match:fda", "skip_keyword:buyout", "no_recent_news"


# ── SKIP phrases (hard block — U15 / spec §1 SKIP_1–SKIP_7) ──────────────────
# If ANY phrase matches (case-insensitive substring) → return SKIP immediately.
# Order matters: first-matching rule determines the catalyst_type label.

_SKIP_RULES: list[tuple[str, list[str]]] = [
    ("buyout_acquisition", [
        "buyout",
        "acquisition",
        "being acquired",
        "merger agreement",
        "to be acquired",
        "will be acquired",
        "agreed to be acquired",
        "agrees to be acquired",
        "tender offer",
        "takeover bid",
        "definitive agreement to buy",
    ]),
    ("secondary_offering", [
        "secondary offering",
        "follow-on offering",
        "underwritten public offering",
        "shelf registration",
        "shelf offering",
        "atm offering",
        "at-the-market offering",
        "dilution",
        "registered direct",
        "direct offering",
        "s-1 registration statement",
        "s-3 registration statement",
    ]),
    ("pump_newsletter", [
        "pump alert",
        "newsletter",
        "text alert",
        "promotional",
        "paid promotion",
        "sponsored stock alert",
        "penny stock alert",
        "hot stock pick",
        "stock promotion",
    ]),
    ("recycled_news", [
        "recycled",
        "reissued",
        "previously announced",
    ]),
    ("five_cent_tick", [
        "five-cent tick pilot",
        "5-cent tick pilot",
        "tick pilot program",
        "nickel spread pilot",
    ]),
]

# ── VERIFIED catalyst patterns (check in order; first match wins) ──────────────
# Only headline+summary pass; no LLM — fast and deterministic.

_VERIFIED_RULES: list[tuple[str, list[str]]] = [
    ("biotech_fda", [
        "fda",
        "clinical",
        "trial results",
        "pdufa",
        "drug approval",
        "phase 1",
        "phase 2",
        "phase 3",
        "nda ",
        "bla ",
        "new drug application",
        "biologics license",
    ]),
    ("earnings_beat", [
        "earnings beat",
        "revenue beat",
        "eps above",
        "beats estimates",
        "beats expectations",
        "above consensus",
    ]),
    # ai_partnership MUST come before contract_win so "AI partnership" is not
    # subsumed by the generic "partnership" phrase in contract_win.
    ("ai_partnership", [
        "ai partnership",
        "artificial intelligence",
        "machine learning partnership",
        "generative ai",
        "large language model",
    ]),
    ("contract_win", [
        "contract win",
        "contract award",
        "agreement with nvidia",
        "agreement with tesla",
        "agreement with apple",
        "agreement with walmart",
        "agreement with amazon",
        "agreement with microsoft",
        "supply agreement",
        "strategic agreement",
        "major contract",
        "strategic partnership",
        "supply partnership",
    ]),
    ("crypto_treasury", [
        "bitcoin treasury",
        "bitcoin reserve",
        "crypto purchase",
        "cryptocurrency reserve",
        "digital asset purchase",
    ]),
    ("ipo_or_reverse_split", [
        "initial public offering",
        " ipo ",
        "spac",
        "reverse split",
        "reverse stock split",
        "reverse merger",
    ]),
    ("activist_investor", [
        "investor stake",
        "13d",
        "13g",
        "activist investor",
        "activist shareholder",
        "major shareholder",
        "significant stake",
        "discloses stake",
        "increases stake",
    ]),
]


# ── classifier ────────────────────────────────────────────────────────────────


class CatalystClassifier:
    """Pure keyword classifier — no external calls, fully synchronous.

    Usage::

        clf = CatalystClassifier()
        result = clf.classify(symbol="AAPL", headline="...", summary="...", source="benzinga")
        # result.status in {"VERIFIED", "SKIP", "UNVERIFIED"}
    """

    def classify(
        self,
        symbol: str,  # noqa: ARG002 — reserved for per-symbol logic
        headline: str,
        summary: str,
        source: str,  # noqa: ARG002 — reserved for source-trust weighting
    ) -> CatalystResult:
        """Classify a single news article.

        Returns:
            CatalystResult with status SKIP, VERIFIED, or UNVERIFIED.
        """
        text = f"{headline} {summary}".lower()

        # Phase 1 — hard block: SKIP if any phrase matches.
        for skip_type, phrases in _SKIP_RULES:
            for phrase in phrases:
                if phrase in text:
                    return CatalystResult(
                        status="SKIP",
                        catalyst_type=skip_type,
                        reason=f"skip_keyword:{phrase}",
                    )

        # Phase 2 — accepted catalyst (first match wins; ordered by priority).
        for cat_type, phrases in _VERIFIED_RULES:
            for phrase in phrases:
                if phrase in text:
                    return CatalystResult(
                        status="VERIFIED",
                        catalyst_type=cat_type,
                        reason=f"keyword_match:{phrase}",
                    )

        return CatalystResult(
            status="UNVERIFIED",
            catalyst_type="none",
            reason="no_recognized_catalyst",
        )


__all__ = ["CatalystClassifier", "CatalystResult"]
