"""NLPCatalystProvider — Phase-7 real implementation of CatalystProvider (spec §1/§13.1).

Replaces StubCatalystProvider. Layered defence-in-depth (fastest/cheapest first):

  1. Reaction-proof gate   — if rvol/roc_pct supplied and below thresholds → UNVERIFIED
  2. SEC EDGAR check       — recent S-1/S-3/424B filing → SKIP (secondary/shelf)
  3. Benzinga headlines    — no key or no headlines → UNVERIFIED (fail-safe)
  4. Keyword SKIP scan     — instant phrase match → SKIP
  5. LLM tag (Haiku 4.5)  → VERIFIED if accepted tag ≥ confidence threshold
                           → SKIP if SKIP tag at any confidence
                           → UNVERIFIED if unknown / low confidence / LLM disabled

Ambiguity always → UNVERIFIED (false-negative is safe: no trade taken, spec §13.1).

Env vars for live operation: BENZINGA_API_KEY, ANTHROPIC_API_KEY.
All sub-components are injectable for fully-offline unit tests.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from adapters.catalyst.benzinga_feed import BenzingaNewsClient
from adapters.catalyst.keyword_filter import scan_for_skip
from adapters.catalyst.llm_classifier import LLMCatalystClassifier
from adapters.catalyst.models import ACCEPTED_TAGS, SKIP_TAGS
from adapters.catalyst.sec_filing import SecFilingClient
from adapters.providers import CatalystProvider, CatalystVerdict

# spec §1 REAL_CATALYST reaction-proof thresholds
_REACTION_RVOL_MIN = Decimal("5")   # Pillar 3 threshold
_REACTION_ROC_MIN = Decimal("10")   # Pillar 4 threshold (%)

_DEFAULT_USER_AGENT = "RossBot-AI-Trader ironriminc@gmail.com"


class NLPCatalystProvider(CatalystProvider):
    """Production catalyst classifier implementing CatalystProvider ABC (spec §1/§13.1).

    When BENZINGA_API_KEY and ANTHROPIC_API_KEY are absent the provider still runs
    layers 1–4 (reaction gate, EDGAR, keyword) and returns UNVERIFIED when no
    headlines can be fetched — the fail-safe state.
    """

    def __init__(
        self,
        news_client: BenzingaNewsClient | None = None,
        sec_client: SecFilingClient | None = None,
        llm_classifier: LLMCatalystClassifier | None = None,
        confidence_threshold: Decimal = Decimal("0.70"),
        filing_lookback_days: int = 30,
        max_headlines: int = 5,
        llm_enabled: bool = True,
    ) -> None:
        self._news = news_client or BenzingaNewsClient()
        self._sec = sec_client or SecFilingClient(user_agent=_DEFAULT_USER_AGENT)
        self._llm = llm_classifier or LLMCatalystClassifier()
        self._threshold = confidence_threshold
        self._lookback_days = filing_lookback_days
        self._max_headlines = max_headlines
        self._llm_enabled = llm_enabled

    async def classify(
        self,
        symbol: str,
        *,
        rvol: Decimal | None = None,
        roc_pct: Decimal | None = None,
    ) -> CatalystVerdict:
        """Classify the catalyst for ``symbol``. Bias to UNVERIFIED/SKIP on ambiguity.

        Optional keyword args:
          rvol    — current relative volume (Pillar 3); UNVERIFIED if below 5×
          roc_pct — current % change from prev close (Pillar 4); UNVERIFIED if below 10%
        """
        # Layer 1 — Reaction-proof gate (spec §13.1): extreme move + headline = real catalyst.
        if rvol is not None and rvol < _REACTION_RVOL_MIN:
            return CatalystVerdict.UNVERIFIED
        if roc_pct is not None and roc_pct < _REACTION_ROC_MIN:
            return CatalystVerdict.UNVERIFIED

        # Layer 2 — SEC EDGAR dilution check (sync I/O in thread; fail-safe on error).
        try:
            has_dilution = await asyncio.to_thread(
                self._sec.has_dilution_filing, symbol, self._lookback_days
            )
            if has_dilution:
                return CatalystVerdict.SKIP  # spec §1 SKIP_3 secondary/shelf
        except Exception:
            pass  # network failure → continue; false-positive block unacceptable

        # Layer 3 — Fetch headlines from Benzinga.
        try:
            headlines = await asyncio.to_thread(
                self._news.get_headlines, symbol, self._max_headlines
            )
        except Exception:
            headlines = []

        if not headlines:
            return CatalystVerdict.UNVERIFIED  # no headline → cannot verify (fail-safe)

        # Layer 4 — Keyword SKIP scan across all headline + body text.
        for item in headlines:
            full_text = f"{item.headline} {item.body}"
            hit = scan_for_skip(full_text)
            if hit is not None:
                return CatalystVerdict.SKIP

        # Layer 5 — LLM classification.
        if not self._llm_enabled:
            return CatalystVerdict.UNVERIFIED  # LLM disabled → conservative

        try:
            result = await asyncio.to_thread(self._llm.classify, symbol, headlines)
        except Exception:
            return CatalystVerdict.UNVERIFIED

        if result.tag in SKIP_TAGS:
            return CatalystVerdict.SKIP

        if result.tag in ACCEPTED_TAGS and result.confidence >= self._threshold:
            return CatalystVerdict.VERIFIED

        return CatalystVerdict.UNVERIFIED  # unknown / low confidence → safe default


__all__ = ["NLPCatalystProvider"]
