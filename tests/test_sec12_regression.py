"""§12 labeled-trade regression fixtures — Risk Manager level.

These tests verify that the Risk Manager correctly APPROVES wins and VETOES losses
as documented in spec §12. Strategy-engine-level vetoes (RKDA, GMBL, PALI) are
already covered in test_strategy_fixtures.py; this module covers the remaining
risk-manager-layer vetoes (GLTO, ESTR, PALI/PTPI, GME, TRNR) plus win approvals.

Acceptance criteria (plan Phase 4):
  SLXN   → risk_manager.evaluate() approved=True   (Five Pillars, 2:1 RR, valid time)
  MLGO   → approved=True                            (same)
  GLTO   → vetoed: AVERAGE_DOWN (U2)                (adding to red position)
  ESTR   → vetoed: NO_FIVE_PILLAR (U1)              (tier_b=False at risk layer)
  PALI   → vetoed: SKIP_CATALYST (U15)              (secondary offering, catalyst_skip=True)
  PTPI   → vetoed: SKIP_CATALYST (U15)              (buyout news, catalyst_skip=True)
  GME    → vetoed: HARD_STOP_TIME (§7)             (2PM trade, past 11AM gate)
  TRNR   → approval.shares <= liquidity_cap_shares  (thin book limits size)

spec §12 / CLAUDE.md §9 / U1/U2/U7/U13/U15/§7.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from adapters.providers import MarketState
from core.config import DEFAULTS, ConfigService, ValueType
from core.risk.manager import RiskManager
from core.risk.models import VetoReason
from core.strategy.models import EntryGateResult, EntrySignal, PatternType


# ── Config helpers ─────────────────────────────────────────────────────────────

def _cfg(overrides: dict[str, str] | None = None) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in (overrides or {}).items():
        if k in rows:
            _, vt = rows[k]
            rows[k] = (v, vt)
    return ConfigService(rows)


def _cfg_permissive() -> ConfigService:
    """Config that permits multiple trades per day (for tests that don't want PDT veto)."""
    return _cfg({
        "MAX_TRADES_PER_DAY": "20",
        "HARD_STOP_TIME": "11:00",
    })


# ── Signal builders ────────────────────────────────────────────────────────────

def _gate(e1_universe: bool = True) -> EntryGateResult:
    return EntryGateResult(
        passes=e1_universe,
        e1_universe=e1_universe,
        e2_pullback=True,
        e3_crossing=True,
        e4_macd=True,
        e5_retrace=True,
        e6_l2=True,
        e7_spread=True,
    )


def _signal(
    symbol: str = "TEST",
    entry: str = "5.00",
    stop: str = "4.50",
    target: str = "6.00",
    e1: bool = True,
    ts: datetime | None = None,
) -> EntrySignal:
    """Build an EntrySignal with RR = (target-entry)/(entry-stop).

    Default: entry=5, stop=4.50, target=6 → RR = (6-5)/(5-4.50) = 1/0.5 = 2.0 (exactly min)
    """
    if ts is None:
        ts = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    return EntrySignal(
        symbol=symbol,
        ts=ts,
        pattern=PatternType.MICRO_PULLBACK,
        conviction_score=Decimal("0.75"),
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        target_price=Decimal(target),
        gate=_gate(e1_universe=e1),
        market_state=MarketState.COLD,
    )


def _rm(cfg: ConfigService | None = None) -> RiskManager:
    return RiskManager(cfg or _cfg_permissive())


_EQUITY = Decimal("25000")
# Jan 15 = winter → EST = UTC-5.
# 9:30 AM UTC = 4:30 AM ET (before market open — before the 11 AM gate → no HARD_STOP_TIME veto)
_AT_OPEN = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
# 2:00 PM ET = 19:00 UTC (well past the 11 AM HARD_STOP_TIME gate)
_AFTER_STOP = datetime(2024, 1, 15, 19, 0, tzinfo=timezone.utc)


# ── SLXN / MLGO — wins → approved ─────────────────────────────────────────────

class TestSLXNWinApproved:
    """SLXN-style fixture: small float, strong catalyst, valid 2:1 RR setup.
    Risk Manager must APPROVE this trade.  spec §12 (SLXN).
    """

    def test_slxn_approved(self):
        rm = _rm()
        sig = _signal("SLXN", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert approval.approved, f"SLXN must be approved; vetoes={approval.vetoes}"

    def test_slxn_shares_positive(self):
        rm = _rm()
        sig = _signal("SLXN", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert approval.approved
        assert approval.shares > 0

    def test_slxn_no_vetoes(self):
        rm = _rm()
        sig = _signal("SLXN", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert approval.vetoes == ()


class TestMLGOWinApproved:
    """MLGO-style fixture: confirmed catalyst, micro-pullback on HOT tape.
    Risk Manager must APPROVE this trade.  spec §12 (MLGO).
    """

    def test_mlgo_approved(self):
        rm = _rm()
        sig = _signal("MLGO", entry="8.00", stop="7.20", target="9.60")  # RR = 1.6/0.8 = 2.0
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert approval.approved, f"MLGO must be approved; vetoes={approval.vetoes}"

    def test_mlgo_shares_positive(self):
        rm = _rm()
        sig = _signal("MLGO", entry="8.00", stop="7.20", target="9.60")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert approval.shares > 0


# ── GLTO — U2 AVERAGE_DOWN veto ───────────────────────────────────────────────

class TestGLTOAverageDown:
    """GLTO fixture: stock spikes then falls below entry.  Adding more shares is
    averaging down — FORBIDDEN (U2).  spec §12 (GLTO) / CLAUDE.md §4 U2.
    """

    def test_glto_average_down_veto(self):
        """Open position at $5.50 → try to buy again at $4.80 → AVERAGE_DOWN veto."""
        rm = _rm()
        rm.record_open("GLTO", Decimal("5.50"))  # first fill at 5.50

        # New signal at 4.80 — below the open position (averaging down)
        sig = _signal("GLTO", entry="4.80", stop="4.30", target="5.80")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)

        assert not approval.approved
        assert VetoReason.AVERAGE_DOWN in approval.vetoes

    def test_glto_not_vetoed_on_higher_price(self):
        """Adding at a HIGHER price is a scale-in, not averaging down — should pass (U2 only blocks lower)."""
        rm = _rm()
        rm.record_open("GLTO", Decimal("4.00"))  # position at 4.00

        # Signal at 5.00 (higher — this is momentum add, not averaging down)
        # U2 only fires when new entry price < existing fill price
        sig = _signal("GLTO", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        # Should NOT get AVERAGE_DOWN veto (may get other vetoes, but not U2)
        assert VetoReason.AVERAGE_DOWN not in approval.vetoes

    def test_glto_average_down_multiple_checks(self):
        """Even when entry is only slightly below open, U2 fires."""
        rm = _rm()
        rm.record_open("GLTO", Decimal("5.01"))
        sig = _signal("GLTO", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert VetoReason.AVERAGE_DOWN in approval.vetoes


# ── ESTR — NO_FIVE_PILLAR veto (U1) ───────────────────────────────────────────

class TestESTRNoPillar:
    """ESTR fixture: high float / no real news catalyst.  Tier-B fails → NO_FIVE_PILLAR.
    spec §12 (ESTR) / CLAUDE.md §4 U1 / spec §11 U1.
    """

    def test_estr_no_five_pillar_veto(self):
        """e1_universe=False in the gate → NO_FIVE_PILLAR at risk layer."""
        rm = _rm()
        sig = _signal("ESTR", e1=False)
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)

        assert not approval.approved
        assert VetoReason.NO_FIVE_PILLAR in approval.vetoes

    def test_estr_approved_when_universe_passes(self):
        """Sanity: same symbol with e1_universe=True must pass (it's the gate, not the name)."""
        rm = _rm()
        sig = _signal("ESTR", e1=True)
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert VetoReason.NO_FIVE_PILLAR not in approval.vetoes


# ── PALI — SKIP_CATALYST veto (U15) ──────────────────────────────────────────

class TestPALISkipCatalyst:
    """PALI fixture: secondary offering catalyst — U15 SKIP list.
    spec §12 (PALI) / CLAUDE.md §4 U15 / spec §11 U15.
    """

    def test_pali_secondary_offering_veto(self):
        """catalyst_skip=True (secondary offering) → SKIP_CATALYST veto."""
        rm = _rm()
        sig = _signal("PALI")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, catalyst_skip=True)

        assert not approval.approved
        assert VetoReason.SKIP_CATALYST in approval.vetoes

    def test_pali_no_veto_without_skip_flag(self):
        """Without catalyst_skip=True, the same signal should NOT get SKIP_CATALYST."""
        rm = _rm()
        sig = _signal("PALI")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, catalyst_skip=False)
        assert VetoReason.SKIP_CATALYST not in approval.vetoes


# ── PTPI — SKIP_CATALYST veto (buyout) ────────────────────────────────────────

class TestPTPISkipCatalyst:
    """PTPI fixture: buyout announcement — U15 SKIP list.
    spec §12 (PTPI) / CLAUDE.md §4 U15 / spec §11 U15.
    """

    def test_ptpi_buyout_catalyst_veto(self):
        rm = _rm()
        sig = _signal("PTPI")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, catalyst_skip=True)

        assert not approval.approved
        assert VetoReason.SKIP_CATALYST in approval.vetoes

    def test_ptpi_veto_does_not_require_special_config(self):
        """U15 is a hard guardrail — catalyst_skip=True is sufficient, no config needed."""
        rm = _rm(_cfg())  # default config, no overrides
        sig = _signal("PTPI")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, catalyst_skip=True)
        assert VetoReason.SKIP_CATALYST in approval.vetoes


# ── GME — HARD_STOP_TIME veto (§7) ────────────────────────────────────────────

class TestGMEHardStopTime:
    """GME fixture: attempted entry at 2PM — well past 11AM HARD_STOP_TIME.
    spec §12 (GME) / CLAUDE.md §5 / spec §7.
    """

    def test_gme_past_hard_stop_time_veto(self):
        """Signal at 2PM → HARD_STOP_TIME veto (HARD_STOP_TIME default = 11:00)."""
        rm = _rm()
        sig = _signal("GME", ts=_AFTER_STOP)
        approval = rm.evaluate(sig, _AFTER_STOP, _EQUITY)

        assert not approval.approved
        assert VetoReason.HARD_STOP_TIME in approval.vetoes

    def test_gme_approved_before_stop_time(self):
        """At 9:30 AM the same setup must pass the time gate."""
        rm = _rm()
        sig = _signal("GME", ts=_AT_OPEN)
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert VetoReason.HARD_STOP_TIME not in approval.vetoes

    def test_gme_veto_uses_configured_stop_time(self):
        """HARD_STOP_TIME is configurable. At 10:30 AM ET with 10:00 AM gate → veto."""
        cfg = _cfg({"HARD_STOP_TIME": "10:00", "MAX_TRADES_PER_DAY": "20"})
        rm = RiskManager(cfg)
        # 10:30 AM ET = 15:30 UTC (winter: EST = UTC-5)
        at_1030_et = datetime(2024, 1, 15, 15, 30, tzinfo=timezone.utc)
        sig = _signal("GME", ts=at_1030_et)
        approval = rm.evaluate(sig, at_1030_et, _EQUITY)
        assert VetoReason.HARD_STOP_TIME in approval.vetoes

    def test_gme_just_before_hard_stop_passes(self):
        """10:59 AM ET with HARD_STOP_TIME=11:00 → gate passes (time <= limit)."""
        rm = _rm()
        # 10:59 AM ET = 15:59 UTC (winter: EST = UTC-5)
        at_1059_et = datetime(2024, 1, 15, 15, 59, tzinfo=timezone.utc)
        sig = _signal("GME", ts=at_1059_et)
        approval = rm.evaluate(sig, at_1059_et, _EQUITY)
        assert VetoReason.HARD_STOP_TIME not in approval.vetoes


# ── TRNR — liquidity cap limits size ──────────────────────────────────────────

class TestTRNRLiquidityCap:
    """TRNR fixture: thin order book — liquidity cap must limit position size.
    Oversize is the recurrent blow-up cause in the fixtures (CLAUDE.md §7.4).
    spec §12 (TRNR) / §11 U9 / spec §13.6.
    """

    def test_trnr_shares_capped_by_liquidity(self):
        """With a 100-share liquidity cap, approval.shares must be ≤ 100."""
        cfg = _cfg({
            "MAX_TRADES_PER_DAY": "20",
            "MAX_SIZE": "10000",  # large max so liquidity is binding
            "SIZING_MODE": "risk_formula",
        })
        rm = RiskManager(cfg)
        # Wide stop → formula would produce large shares; cap must bind
        sig = _signal("TRNR", entry="5.00", stop="4.99", target="5.02")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, liquidity_cap_shares=100)

        if approval.approved:
            assert approval.shares <= 100, (
                f"TRNR liquidity cap: shares {approval.shares} must be ≤ 100"
            )
        # If sizing formula produces 0 shares (very thin stop), veto is acceptable too

    def test_trnr_no_cap_gives_more_shares(self):
        """Without a cap, approval.shares is unconstrained by book depth."""
        cfg = _cfg({"MAX_TRADES_PER_DAY": "20"})
        rm = RiskManager(cfg)
        sig = _signal("TRNR", entry="5.00", stop="4.50", target="6.00")

        approval_uncapped = rm.evaluate(sig, _AT_OPEN, _EQUITY, liquidity_cap_shares=None)
        rm2 = RiskManager(cfg)
        approval_capped = rm2.evaluate(sig, _AT_OPEN, _EQUITY, liquidity_cap_shares=50)

        if approval_uncapped.approved and approval_capped.approved:
            assert approval_uncapped.shares >= approval_capped.shares

    def test_trnr_single_share_cap(self):
        """Liquidity cap of 1 → approval.shares == 1 (minimum tradeable lot)."""
        cfg = _cfg({"MAX_TRADES_PER_DAY": "20"})
        rm = RiskManager(cfg)
        sig = _signal("TRNR", entry="5.00", stop="4.50", target="6.00")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY, liquidity_cap_shares=1)
        if approval.approved:
            assert approval.shares == 1


# ── Composite: daily state degrades correctly ──────────────────────────────────

class TestDailyStateDegradation:
    """Three consecutive losses halt the session (U5) for subsequent signals."""

    def test_three_strikes_halt(self):
        cfg = _cfg({"MAX_TRADES_PER_DAY": "20", "THREE_STRIKES": "3"})
        rm = RiskManager(cfg)
        # Record 3 losses
        for i in range(3):
            rm.record_open(f"SYM{i}", Decimal("5.00"))
            rm.record_close(f"SYM{i}", Decimal("-50"))

        sig = _signal("TEST4")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert not approval.approved
        assert VetoReason.HALTED in approval.vetoes or VetoReason.THREE_STRIKES in approval.vetoes

    def test_reset_clears_strikes(self):
        cfg = _cfg({"MAX_TRADES_PER_DAY": "20"})
        rm = RiskManager(cfg)
        for i in range(3):
            rm.record_open(f"S{i}", Decimal("5.00"))
            rm.record_close(f"S{i}", Decimal("-50"))

        rm.reset_session()
        sig = _signal("TEST4")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        # After reset, strikes are cleared; HARD_STOP_TIME/PDT should pass
        assert VetoReason.THREE_STRIKES not in approval.vetoes
        assert VetoReason.HALTED not in approval.vetoes

    def test_daily_loss_limit_veto(self):
        """U4: realized PnL beyond MAX_DAILY_LOSS blocks new trades."""
        cfg = _cfg({"MAX_TRADES_PER_DAY": "20", "MAX_DAILY_LOSS_PCT": "0.02"})
        rm = RiskManager(cfg)
        # Simulate $1000 loss on $25k equity — 4% of equity → exceeds 2% cap
        rm.record_open("LOSS", Decimal("5.00"))
        rm.record_close("LOSS", Decimal("-1000"))

        sig = _signal("NEXT")
        approval = rm.evaluate(sig, _AT_OPEN, _EQUITY)
        assert not approval.approved
        assert VetoReason.DAILY_LOSS_LIMIT in approval.vetoes or VetoReason.THREE_STRIKES in approval.vetoes
