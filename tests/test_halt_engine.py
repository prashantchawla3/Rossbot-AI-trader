"""Tests for core.halt — halt resumption engine. spec §12A / §13.7.

Acceptance criteria:
  - Halt-down resumption (EX5) blocked unless VWAP reclaimed.
  - HALT_TYPE=LULD_DOWN always blocked (even if resume_price >= pre_halt).
  - ARM/CTRM/PHVS-style dip-and-rip fixtures trigger ENTER.
  - Pre-halt entries require HOT + buyer_on_bid + within-band-distance.
  - POST_HALT with no green prints → SKIP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.providers import MarketState
from core.config import ConfigService, HaltMode
from core.halt.engine import evaluate_halt_resumption, evaluate_pre_halt_entry
from core.halt.models import HaltDecision, HaltEvent, HaltType, PreHaltSignal, ResumeQuote


# ── Helpers ───────────────────────────────────────────────────────────────────

_TS = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)


def _cfg(halt_mode: str = "post_halt") -> ConfigService:
    svc = ConfigService.from_defaults()
    svc._rows["HALT_MODE"] = (halt_mode, svc._rows["HALT_MODE"][1])
    return svc


def _halt_up(pre_price: Decimal = Decimal("7.00"), vwap: Decimal = Decimal("6.50")) -> HaltEvent:
    return HaltEvent(
        symbol="CTRM",
        ts=_TS,
        halt_type=HaltType.LULD_UP,
        pre_halt_price=pre_price,
        vwap=vwap,
    )


def _halt_down(pre_price: Decimal = Decimal("7.00"), vwap: Decimal = Decimal("7.50")) -> HaltEvent:
    return HaltEvent(
        symbol="PHVS",
        ts=_TS,
        halt_type=HaltType.LULD_DOWN,
        pre_halt_price=pre_price,
        vwap=vwap,
    )


def _resume(
    price: Decimal,
    green_prints: bool = True,
    current_vwap: Decimal = Decimal("6.50"),
) -> ResumeQuote:
    return ResumeQuote(
        symbol="TEST",
        ts=_TS,
        resume_price=price,
        green_prints=green_prints,
        current_vwap=current_vwap,
    )


# ── POST_HALT (default) — happy-path fixtures ─────────────────────────────────


class TestPostHaltHappyPath:
    """ARM/CTRM/PHVS/KALA/SNGX dip-and-rip: resume >= prior price + green prints → ENTER."""

    def test_ctrm_style_halt_up_enters(self) -> None:
        """CTRM: halted on way up; resumes above pre-halt price with green prints."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("6.41"))
        resume = _resume(price=Decimal("7.00"), green_prints=True, current_vwap=Decimal("6.20"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.ENTER

    def test_phvs_style_enters(self) -> None:
        """PHVS: $5.41 → $7.00 halt-up resumption."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("5.41"))
        resume = _resume(price=Decimal("5.80"), green_prints=True, current_vwap=Decimal("5.20"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.ENTER

    def test_flat_resume_at_pre_halt_price_enters(self) -> None:
        """Resume exactly at pre_halt price with green prints → still ENTER."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("10.00"))
        resume = _resume(price=Decimal("10.00"), green_prints=True, current_vwap=Decimal("9.50"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.COLD)
        assert decision == HaltDecision.ENTER

    def test_market_state_cold_still_enters_post_halt(self) -> None:
        """POST_HALT doesn't care about market state; only HALT_MODE matters."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("8.00"))
        resume = _resume(price=Decimal("8.50"), green_prints=True, current_vwap=Decimal("7.80"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.COLD)
        assert decision == HaltDecision.ENTER


class TestPostHaltSkipConditions:
    """Resume below pre-halt price or no green prints → SKIP."""

    def test_resume_below_pre_halt_skips(self) -> None:
        """Bullish halt but resumes lower than pre-halt → weakness → SKIP."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("7.08"))
        resume = _resume(price=Decimal("7.01"), green_prints=True, current_vwap=Decimal("6.50"))
        # resume < pre_halt → SKIP (even with green prints)
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.SKIP

    def test_no_green_prints_skips(self) -> None:
        """Resume above pre-halt price but no green prints → SKIP."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("7.00"))
        resume = _resume(price=Decimal("7.50"), green_prints=False, current_vwap=Decimal("6.50"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.SKIP


class TestEX5HaltDownBlocked:
    """EX5: halt-down resumptions are BLOCKED unless VWAP is reclaimed. spec §12A EX5."""

    def test_halt_down_no_vwap_reclaim_blocked(self) -> None:
        """EX5: LULD_DOWN halt resumes below VWAP → BLOCKED."""
        cfg = _cfg("post_halt")
        halt = _halt_down(pre_price=Decimal("7.00"), vwap=Decimal("7.50"))
        # Resume at 6.50 — below pre_halt AND below VWAP
        resume = _resume(price=Decimal("6.50"), green_prints=True, current_vwap=Decimal("7.20"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.BLOCKED

    def test_halt_down_with_vwap_reclaim_allowed(self) -> None:
        """EX5 exception: halt-down but resumes ABOVE VWAP (reclaimed) → ENTER allowed."""
        cfg = _cfg("post_halt")
        halt = _halt_down(pre_price=Decimal("7.00"), vwap=Decimal("6.80"))
        # Resume at 7.10 — ABOVE current_vwap (6.90) → VWAP reclaimed
        resume = _resume(price=Decimal("7.10"), green_prints=True, current_vwap=Decimal("6.90"))
        # halt_type=LULD_DOWN normally means is_halt_down=True;
        # but resume_price (7.10) > current_vwap (6.90) → vwap_reclaimed → not BLOCKED.
        # resume_price (7.10) >= pre_halt_price (7.00) → ENTER
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.ENTER

    def test_unknown_halt_type_treated_as_down(self) -> None:
        """UNKNOWN halt type is treated as LULD_DOWN (conservative). spec §13.7."""
        cfg = _cfg("post_halt")
        halt = HaltEvent(
            symbol="UNKN",
            ts=_TS,
            halt_type=HaltType.UNKNOWN,
            pre_halt_price=Decimal("5.00"),
            vwap=Decimal("5.50"),
        )
        resume = _resume(price=Decimal("4.50"), green_prints=True, current_vwap=Decimal("5.10"))
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.BLOCKED

    def test_resume_price_below_pre_halt_blocked_regardless_of_halt_type(self) -> None:
        """Even LULD_UP halt where resume < pre_halt → is_halt_down=True → BLOCKED if no VWAP."""
        cfg = _cfg("post_halt")
        halt = _halt_up(pre_price=Decimal("10.00"), vwap=Decimal("9.00"))
        resume = _resume(price=Decimal("9.00"), green_prints=True, current_vwap=Decimal("9.50"))
        # resume_price (9.00) < pre_halt (10.00) AND resume (9.00) < vwap (9.50) → BLOCKED
        decision = evaluate_halt_resumption(halt, resume, cfg, MarketState.HOT)
        assert decision == HaltDecision.BLOCKED


# ── PRE_HALT mode ─────────────────────────────────────────────────────────────


class TestPreHaltEntry:
    """PRE_HALT entries only fire in HOT + buyer_on_bid + within-band. spec §12A."""

    def _pre_halt_signal(
        self,
        buyer: bool = True,
        distance_pct: Decimal = Decimal("0.5"),
        price: Decimal = Decimal("7.00"),
        vwap: Decimal = Decimal("6.50"),
    ) -> PreHaltSignal:
        return PreHaltSignal(
            symbol="ARM",
            ts=_TS,
            current_price=price,
            luld_band=Decimal("7.50"),
            distance_to_band_pct=distance_pct,
            buyer_on_bid=buyer,
            vwap=vwap,
        )

    def test_hot_with_buyer_and_near_band_enters(self) -> None:
        cfg = _cfg("pre_halt")
        sig = self._pre_halt_signal(buyer=True, distance_pct=Decimal("0.5"))
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.HOT)
        assert decision == HaltDecision.ENTER

    def test_cold_market_skips(self) -> None:
        """PRE_HALT requires HOT — COLD always SKIP."""
        cfg = _cfg("pre_halt")
        sig = self._pre_halt_signal(buyer=True)
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.COLD)
        assert decision == HaltDecision.SKIP

    def test_post_halt_mode_skips_pre_halt_eval(self) -> None:
        """evaluate_pre_halt_entry with HALT_MODE=post_halt → SKIP."""
        cfg = _cfg("post_halt")
        sig = self._pre_halt_signal(buyer=True)
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.HOT)
        assert decision == HaltDecision.SKIP

    def test_no_buyer_on_bid_skips(self) -> None:
        cfg = _cfg("pre_halt")
        sig = self._pre_halt_signal(buyer=False)
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.HOT)
        assert decision == HaltDecision.SKIP

    def test_too_far_from_band_skips(self) -> None:
        """Distance to band > PRE_HALT_BAND_ENTRY_PCT (1.0%) → SKIP."""
        cfg = _cfg("pre_halt")
        sig = self._pre_halt_signal(buyer=True, distance_pct=Decimal("3.0"))
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.HOT)
        assert decision == HaltDecision.SKIP

    def test_price_below_vwap_blocked(self) -> None:
        """EX5 guard: price below VWAP pre-halt → BLOCKED (downward flush risk)."""
        cfg = _cfg("pre_halt")
        sig = self._pre_halt_signal(
            buyer=True, price=Decimal("6.20"), vwap=Decimal("6.80")
        )
        decision = evaluate_pre_halt_entry(sig, cfg, MarketState.HOT)
        assert decision == HaltDecision.BLOCKED
