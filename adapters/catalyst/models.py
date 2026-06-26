"""Catalyst-detection domain models — spec §1 §13.1."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class CatalystTag(StrEnum):
    """All classification tags produced by the classifier (accepted + SKIP — spec §1)."""

    # ---- Accepted (tradeable) catalysts ----
    BIOTECH_FDA = "biotech_clinical_or_fda"
    EARNINGS_BEAT = "earnings_beat"
    MAJOR_CONTRACT = "major_contract_win"
    AI_PARTNERSHIP = "ai_partnership"
    CRYPTO_TREASURY = "crypto_treasury"
    SPACE_THEME = "space_theme"
    VIRUS_OUTBREAK = "virus_outbreak_theme"
    PRIVATE_PLACEMENT = "private_placement"
    REVERSE_SPLIT = "recent_reverse_split"
    RECENT_IPO = "recent_ipo"
    RECENT_SPAC = "recent_spac"
    INVESTOR_STAKE = "investor_stake_13d_13g"

    # ---- SKIP categories §1 SKIP_1–SKIP_7 / U15 — hard blocks ----
    BUYOUT_SKIP = "buyout_skip"
    MERGER_AMBIGUOUS_SKIP = "merger_ambiguous_skip"
    SECONDARY_OFFERING_SKIP = "secondary_offering_skip"
    PUMP_SKIP = "pump_skip"
    RECYCLED_PR_SKIP = "recycled_pr_skip"
    FIVE_CENT_TICK_SKIP = "five_cent_tick_skip"
    LARGE_CAP_SKIP = "large_cap_skip"

    # ---- Uncertain ----
    UNKNOWN = "unknown"


# Tags that map to CatalystVerdict.VERIFIED (real, tradeable catalyst).
ACCEPTED_TAGS: frozenset[CatalystTag] = frozenset({
    CatalystTag.BIOTECH_FDA,
    CatalystTag.EARNINGS_BEAT,
    CatalystTag.MAJOR_CONTRACT,
    CatalystTag.AI_PARTNERSHIP,
    CatalystTag.CRYPTO_TREASURY,
    CatalystTag.SPACE_THEME,
    CatalystTag.VIRUS_OUTBREAK,
    CatalystTag.PRIVATE_PLACEMENT,
    CatalystTag.REVERSE_SPLIT,
    CatalystTag.RECENT_IPO,
    CatalystTag.RECENT_SPAC,
    CatalystTag.INVESTOR_STAKE,
})

# Tags that map to CatalystVerdict.SKIP (hard block — U15, spec §1 SKIP_1–SKIP_7).
SKIP_TAGS: frozenset[CatalystTag] = frozenset({
    CatalystTag.BUYOUT_SKIP,
    CatalystTag.MERGER_AMBIGUOUS_SKIP,
    CatalystTag.SECONDARY_OFFERING_SKIP,
    CatalystTag.PUMP_SKIP,
    CatalystTag.RECYCLED_PR_SKIP,
    CatalystTag.FIVE_CENT_TICK_SKIP,
    CatalystTag.LARGE_CAP_SKIP,
})


@dataclass(frozen=True)
class NewsItem:
    """One headline from the news feed."""

    headline: str
    body: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""  # ISO 8601 ET


@dataclass(frozen=True)
class CatalystResult:
    """Full classification result before mapping to CatalystVerdict."""

    tag: CatalystTag
    confidence: Decimal  # 0.0 – 1.0
    reasoning: str = ""
    source: str = ""  # "keyword" | "sec_filing" | "llm" | "none" | "llm_error"


__all__ = [
    "ACCEPTED_TAGS",
    "SKIP_TAGS",
    "CatalystResult",
    "CatalystTag",
    "NewsItem",
]
