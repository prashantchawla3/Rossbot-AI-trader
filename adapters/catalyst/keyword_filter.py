"""Instant keyword-based SKIP filter (no API call) — spec §1 SKIP_1–SKIP_7.

Defence-in-depth layer 1. Runs first, before any HTTP call, for maximum speed.
Conservative: only match phrases that very strongly imply the SKIP category. A
false-positive (marking a good catalyst as SKIP) is acceptable; a false-negative
(missing a SKIP) is recoverable via the SEC filing check and LLM layers.
"""

from __future__ import annotations

from dataclasses import dataclass

from adapters.catalyst.models import CatalystTag

# Each rule: (tag, list of lowercase phrases — all are substring matches on lowered text).
_SKIP_RULES: list[tuple[CatalystTag, list[str]]] = [
    # §1 SKIP_1: buyout / being-acquired (price pins, zero momentum).
    (CatalystTag.BUYOUT_SKIP, [
        "acquisition agreement",
        "to acquire",
        "to be acquired",      # catches "agrees to be acquired", "agreed to be acquired", etc.
        "being acquired",
        "will be acquired",
        "buyout",
        "takeover bid",
        "tender offer",
        "to purchase all outstanding shares",
        "definitive agreement to buy",
        "agreement to be purchased",
    ]),
    # §1 SKIP_3: secondary / shelf offerings (instant momentum killer — PALI fixture).
    (CatalystTag.SECONDARY_OFFERING_SKIP, [
        "secondary offering",
        "follow-on offering",
        "underwritten public offering",
        "registered direct offering",
        "shelf registration",
        "shelf offering",
        "s-1 registration statement",
        "s-3 registration statement",
        "424b prospectus",
        "direct offering",
        "million shares at $",     # "prices offering of N million shares at $X"
        "share offering at",
        "stock offering at",
    ]),
    # §1 SKIP_4: pump-and-dump newsletter promotions.
    (CatalystTag.PUMP_SKIP, [
        "newsletter promotion",
        "stock promotion",
        "paid promotion",
        "sponsored stock alert",
        "penny stock alert",
        "email promotion",
        "hot stock pick",
    ]),
    # §1 SKIP_6: five-cent tick pilot mandates 5c spreads — scalp-unsafe.
    (CatalystTag.FIVE_CENT_TICK_SKIP, [
        "5-cent tick pilot",
        "five cent tick pilot",
        "tick pilot program",
        "nickel spread pilot",
    ]),
]


@dataclass(frozen=True)
class KeywordHit:
    """Result when a SKIP keyword is matched."""

    tag: CatalystTag
    matched_phrase: str


def scan_for_skip(text: str) -> KeywordHit | None:
    """Scan ``text`` for hard-block SKIP keyword phrases.

    Case-insensitive substring match. Returns the first hit (most specific SKIP
    tag wins) or ``None`` if no SKIP phrase matched.
    """
    lowered = text.lower()
    for tag, phrases in _SKIP_RULES:
        for phrase in phrases:
            if phrase in lowered:
                return KeywordHit(tag=tag, matched_phrase=phrase)
    return None


__all__ = ["KeywordHit", "scan_for_skip"]
