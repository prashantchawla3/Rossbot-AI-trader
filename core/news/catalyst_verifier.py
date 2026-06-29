"""CatalystVerifier — looks up live news for a symbol and classifies it.

Wired into Tier-B Pillar-5 (spec §1/§13.1).  Decision hierarchy:

  1. No news in cache → UNVERIFIED(reason="no_recent_news")
  2. Any article → SKIP  → SKIP wins immediately (hard block U15)
  3. Any article → VERIFIED → VERIFIED (highest-priority match across all articles)
  4. All articles → UNVERIFIED → UNVERIFIED(reason="no_recognized_catalyst")

Bias: a single SKIP in any article hard-blocks the symbol.  UNVERIFIED is the
safe default for scanners that lack a news feed or during reconnect windows.
"""

from __future__ import annotations

import logging

from core.news.catalyst_classifier import CatalystClassifier, CatalystResult
from core.news.news_stream import NewsStreamAdapter

log = logging.getLogger(__name__)

_DEFAULT_LOOKBACK = 60  # minutes — covers pre-market + first hour


class CatalystVerifier:
    """Verifies the catalyst for a symbol using the live Alpaca/Benzinga stream.

    Designed to be instantiated once at startup (singleton stored on ``app.state``)
    and called from the scanner / demo engine every scan cycle.
    """

    def __init__(
        self,
        news_stream: NewsStreamAdapter,
        classifier: CatalystClassifier | None = None,
        lookback_minutes: int = _DEFAULT_LOOKBACK,
    ) -> None:
        self._stream = news_stream
        self._classifier = classifier or CatalystClassifier()
        self._lookback_minutes = lookback_minutes

    async def verify(self, symbol: str) -> CatalystResult:
        """Return the Pillar-5 verdict for ``symbol``.

        Reads the in-memory news cache — no network call in the hot path.
        """
        items = await self._stream.get_recent_news(symbol, self._lookback_minutes)

        if not items:
            result = CatalystResult(
                status="UNVERIFIED",
                catalyst_type="none",
                reason="no_recent_news",
            )
            log.info(
                "catalyst_verify symbol=%s status=%s reason=%s",
                symbol,
                result.status,
                result.reason,
            )
            return result

        skip_result: CatalystResult | None = None
        verified_result: CatalystResult | None = None

        for item in items:
            r = self._classifier.classify(
                symbol=symbol,
                headline=item.headline,
                summary=item.summary,
                source=item.source,
            )
            log.info(
                "catalyst_verify symbol=%s status=%s type=%s reason=%s headline=%r",
                symbol,
                r.status,
                r.catalyst_type,
                r.reason,
                item.headline[:60],
            )
            if r.status == "SKIP" and skip_result is None:
                skip_result = r
            elif r.status == "VERIFIED" and verified_result is None:
                verified_result = r

        # SKIP hard-blocks even if other articles are VERIFIED (U15)
        if skip_result is not None:
            return skip_result
        if verified_result is not None:
            return verified_result

        return CatalystResult(
            status="UNVERIFIED",
            catalyst_type="none",
            reason="no_recognized_catalyst",
        )


__all__ = ["CatalystVerifier"]
