"""Claude Haiku 4.5 catalyst classifier — spec §13.1.

Model: claude-haiku-4-5-20251001
Pricing (verified 2026-06-26 via platform.claude.com/docs/en/about-claude/pricing):
  Input: $1.00 / MTok | Output: $5.00 / MTok
A single classification call ≈ 600 input + 100 output tokens ≈ $0.001.

Requires ANTHROPIC_API_KEY env var. Falls back to CatalystResult(UNKNOWN, 0)
on any error (missing key, import failure, API error, malformed response).
``client`` argument enables dependency injection for offline tests.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from adapters.catalyst.models import CatalystResult, CatalystTag, NewsItem

_SYSTEM_PROMPT = (
    "You are a financial news catalyst classifier for a day-trading risk system. "
    "Return ONLY a JSON object — no prose, no markdown fences — with exactly three keys: "
    "\"tag\" (string from the allowed list), \"confidence\" (float 0.0–1.0), "
    "\"reasoning\" (one sentence, max 20 words)."
)

_ALL_TAG_VALUES: list[str] = [t.value for t in CatalystTag]

_USER_TEMPLATE = """\
Classify the news catalyst for ticker {symbol}.

Headlines:
{headlines}

ALLOWED TAGS:
  biotech_clinical_or_fda  — FDA approval/rejection/trial topline/PDUFA date
  earnings_beat            — earnings beat above expectations
  major_contract_win       — major customer win (Nvidia/Apple/Tesla/Walmart-tier)
  ai_partnership           — significant AI product or partnership announcement
  crypto_treasury          — bitcoin or crypto treasury acquisition
  space_theme              — space sector news
  virus_outbreak_theme     — new virus or outbreak
  private_placement        — PIPE or private placement (may carry dilution nuance)
  recent_reverse_split     — recent reverse stock split
  recent_ipo               — recent IPO
  recent_spac              — recent SPAC merger or listing
  investor_stake_13d_13g   — >10% investor stake disclosed via 13D/13G

  buyout_skip              — company is the ACQUISITION TARGET (price pins, no momentum)
  merger_ambiguous_skip    — merger language but unclear who acquires whom
  secondary_offering_skip  — new shares being sold publicly (dilutive; kills momentum)
  pump_skip                — paid newsletter or email promotion campaign
  recycled_pr_skip         — reissued or recycled old press release
  five_cent_tick_skip      — stock subject to mandatory 5-cent tick pilot program
  large_cap_skip           — large-cap heavily HFT-dominated stock

  unknown                  — cannot determine type or not enough information

RULES:
- Use a SKIP tag whenever the headline clearly implies that category.
- Use an ACCEPTED tag ONLY if confidence >= 0.70 and the evidence is unambiguous.
- Default to "unknown" if you are unsure. Bias strongly toward "unknown".
- "confidence" for unknown should always be <= 0.50.
"""


class LLMCatalystClassifier:
    """Zero-shot Claude Haiku 4.5 classifier for catalyst type (spec §13.1).

    ``client`` is an anthropic.Anthropic-compatible object injected for tests.
    Falls back to CatalystResult(UNKNOWN, 0) on any failure.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
        client: object | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._client = client  # injected; None → lazy-init on first call

    def _get_client(self) -> object | None:
        if not self._api_key:
            return None
        if self._client is None:
            try:
                import anthropic  # optional dependency
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                return None
        return self._client

    def classify(self, symbol: str, headlines: list[NewsItem]) -> CatalystResult:
        """Synchronous classification call (run via asyncio.to_thread in async contexts).

        Returns CatalystResult(UNKNOWN, 0) on any error or when no API key is configured.
        """
        _unknown = CatalystResult(tag=CatalystTag.UNKNOWN, confidence=Decimal("0"), source="none")

        client = self._get_client()
        if client is None or not headlines:
            return _unknown

        headline_block = "\n".join(f"- {h.headline}" for h in headlines[:5])
        user_msg = _USER_TEMPLATE.format(symbol=symbol.upper(), headlines=headline_block)

        try:
            response = client.messages.create(  # type: ignore[attr-defined]
                model=self._model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw_text: str = response.content[0].text.strip()
        except Exception:
            return CatalystResult(tag=CatalystTag.UNKNOWN, confidence=Decimal("0"), source="llm_error")

        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            parts = raw_text.split("```")
            raw_text = parts[1] if len(parts) > 1 else parts[0]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        try:
            obj = json.loads(raw_text)
        except Exception:
            return CatalystResult(tag=CatalystTag.UNKNOWN, confidence=Decimal("0"), source="llm_error")

        tag_str = str(obj.get("tag", "unknown"))
        try:
            tag = CatalystTag(tag_str)
        except ValueError:
            tag = CatalystTag.UNKNOWN

        try:
            confidence = Decimal(str(obj.get("confidence", 0.0)))
        except Exception:
            confidence = Decimal("0")

        reasoning = str(obj.get("reasoning", ""))
        return CatalystResult(tag=tag, confidence=confidence, reasoning=reasoning, source="llm")


__all__ = ["LLMCatalystClassifier"]
