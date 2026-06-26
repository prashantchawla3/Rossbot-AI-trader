"""Pre-market readiness checklist — automated gate before enabling live capital.

All checks must pass before LiveSession is allowed to run. Each item is independent;
a failing item does NOT short-circuit the rest (we want the full picture, not early exit).

Checks (in order):
  1. LIVE_ENABLED     config.get_bool("LIVE_ENABLED") must be True (U6 admin sign-off).
  2. U6_GATE          SimulatorGate.satisfied (≥10 days @ ≥60% accuracy).
  3. ACCOUNT_TYPE     account_type != UNKNOWN (confirmed margin or cash).
  4. BUYING_POWER     buying_power >= READINESS_MIN_BUYING_POWER.
  5. PDT_EQUITY       if margin and pdt_restricted: warn (not blocking, just logged).
  6. CAPITAL_TIER     tier != FULL on first session (protection against misconfiguration).
  7. CLOCK_DRIFT      NTP drift < CLOCK_DRIFT_MAX_MS ms.
  8. DATA_FEED        data adapter returns a quote within FEED_CHECK_TIMEOUT_S seconds.

spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6 hard-gates.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog

from adapters.base import AccountState, AccountType, BrokerAdapter, MarketDataAdapter
from core.backtest.sim_gate import SimulatorGate
from core.config import ConfigService
from core.live.models import CapitalTier, ReadinessItem, ReadinessResult

log = structlog.get_logger(__name__)

_FEED_CHECK_TIMEOUT_S = 10  # seconds to wait for at least one quote from data adapter
_PROBE_SYMBOL = "SPY"       # liquid symbol used to probe the data feed


class ReadinessChecker:
    """Runs all pre-market readiness checks and returns a ReadinessResult.

    Usage::

        checker = ReadinessChecker(config, sim_gate, broker, market_data)
        result = await checker.check_all()
        if not result.all_passed:
            raise RuntimeError(result.summary())

    spec Phase 6 / §11 U6.
    """

    def __init__(
        self,
        config: ConfigService,
        sim_gate: SimulatorGate,
        broker: BrokerAdapter,
        market_data: MarketDataAdapter,
    ) -> None:
        self._cfg = config
        self._gate = sim_gate
        self._broker = broker
        self._data = market_data

    async def check_all(self) -> ReadinessResult:
        """Run all checks and return the full ReadinessResult.

        All checks run regardless of earlier failures so the operator sees the
        complete picture at once (no fail-fast).
        """
        account = await self._safe_account_state()

        items: list[ReadinessItem] = [
            self._check_live_enabled(),
            self._check_u6_gate(),
            self._check_account_type(account),
            self._check_buying_power(account),
            self._check_pdt_equity(account),
            self._check_capital_tier(),
            await self._check_clock_drift(),
            await self._check_data_feed(),
        ]
        return ReadinessResult(items=tuple(items))

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_live_enabled(self) -> ReadinessItem:
        enabled = self._cfg.get_bool("LIVE_ENABLED")
        return ReadinessItem(
            name="LIVE_ENABLED",
            passed=enabled,
            detail=(
                "LIVE_ENABLED=true — admin sign-off recorded"
                if enabled
                else "LIVE_ENABLED=false — set to true after client sign-off to enable live"
            ),
        )

    def _check_u6_gate(self) -> ReadinessItem:
        satisfied = self._gate.satisfied
        return ReadinessItem(
            name="U6_GATE",
            passed=satisfied,
            detail=self._gate.status_summary,
        )

    def _check_account_type(self, account: AccountState) -> ReadinessItem:
        known = account.account_type is not AccountType.UNKNOWN
        return ReadinessItem(
            name="ACCOUNT_TYPE",
            passed=known,
            detail=(
                f"Account type confirmed: {account.account_type}"
                if known
                else "Account type UNKNOWN — confirm margin or cash with broker before going live"
            ),
        )

    def _check_buying_power(self, account: AccountState) -> ReadinessItem:
        minimum = self._cfg.get_decimal("READINESS_MIN_BUYING_POWER")
        ok = account.buying_power >= minimum
        return ReadinessItem(
            name="BUYING_POWER",
            passed=ok,
            detail=(
                f"Buying power ${account.buying_power:,.2f} ≥ minimum ${minimum:,.2f}"
                if ok
                else f"Buying power ${account.buying_power:,.2f} below minimum ${minimum:,.2f}"
            ),
        )

    def _check_pdt_equity(self, account: AccountState) -> ReadinessItem:
        """PDT equity check — warning only (does not block).

        A margin account with equity < $25k is PDT-restricted (≤3 day-trades/5 days).
        Cash accounts have different restrictions. This is advisory; the risk manager's
        MAX_TRADES_PER_DAY gate is the enforcement point.
        """
        if account.account_type is not AccountType.MARGIN:
            return ReadinessItem(
                name="PDT_EQUITY",
                passed=True,
                detail=f"Non-margin account ({account.account_type}); PDT rule differs — confirm trade-count limits",
            )
        pdt_floor = self._cfg.get_decimal("READINESS_MIN_EQUITY")
        ok = account.equity >= pdt_floor
        return ReadinessItem(
            name="PDT_EQUITY",
            passed=True,  # advisory only — risk manager enforces MAX_TRADES_PER_DAY
            detail=(
                f"Equity ${account.equity:,.2f} ≥ PDT floor ${pdt_floor:,.2f} — unlimited day-trades"
                if ok
                else (
                    f"WARNING: Equity ${account.equity:,.2f} < PDT floor ${pdt_floor:,.2f}; "
                    "account is PDT-restricted (≤3 day-trades/5 days). "
                    "Set MAX_TRADES_PER_DAY to match your remaining day-trade count."
                )
            ),
        )

    def _check_capital_tier(self) -> ReadinessItem:
        """Warn if CAPITAL_RAMP_TIER is set to FULL on what appears to be a first session."""
        raw = self._cfg.get_str("CAPITAL_RAMP_TIER").upper()
        try:
            tier = CapitalTier(raw)
        except ValueError:
            return ReadinessItem(
                name="CAPITAL_TIER",
                passed=False,
                detail=f"Unknown CAPITAL_RAMP_TIER={raw!r}; must be MICRO, STARTER, or FULL",
            )
        if tier is CapitalTier.FULL:
            return ReadinessItem(
                name="CAPITAL_TIER",
                passed=True,
                detail="CAPITAL_RAMP_TIER=FULL — ensure this is intentional (not a first live session)",
            )
        return ReadinessItem(
            name="CAPITAL_TIER",
            passed=True,
            detail=f"CAPITAL_RAMP_TIER={tier} — appropriate staged capital ramp in effect",
        )

    async def _check_clock_drift(self) -> ReadinessItem:
        """Check NTP clock drift is within CLOCK_DRIFT_MAX_MS."""
        max_ms = self._cfg.get_int("CLOCK_DRIFT_MAX_MS")
        try:
            import ntplib  # type: ignore[import-untyped]

            resp = await asyncio.to_thread(ntplib.NTPClient().request, "pool.ntp.org", version=3)
            drift_ms = abs(resp.offset * 1000)
            ok = drift_ms < max_ms
            return ReadinessItem(
                name="CLOCK_DRIFT",
                passed=ok,
                detail=(
                    f"Clock drift {drift_ms:.1f}ms (max {max_ms}ms)"
                    if ok
                    else f"Clock drift {drift_ms:.1f}ms EXCEEDS max {max_ms}ms — sync system clock"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return ReadinessItem(
                name="CLOCK_DRIFT",
                passed=False,
                detail=f"NTP check failed: {exc} — ensure network access and ntplib installed",
            )

    async def _check_data_feed(self) -> ReadinessItem:
        """Probe the data feed with a SPY quote within FEED_CHECK_TIMEOUT_S seconds."""
        try:
            quote = await asyncio.wait_for(
                self._data.get_quote(_PROBE_SYMBOL),
                timeout=_FEED_CHECK_TIMEOUT_S,
            )
            ok = quote.bid > Decimal("0") and quote.ask > Decimal("0")
            return ReadinessItem(
                name="DATA_FEED",
                passed=ok,
                detail=(
                    f"Data feed live: {_PROBE_SYMBOL} bid={quote.bid} ask={quote.ask}"
                    if ok
                    else f"Data feed returned zero-price quote for {_PROBE_SYMBOL}"
                ),
            )
        except TimeoutError:
            return ReadinessItem(
                name="DATA_FEED",
                passed=False,
                detail=f"Data feed timed out after {_FEED_CHECK_TIMEOUT_S}s — check connection",
            )
        except Exception as exc:  # noqa: BLE001
            return ReadinessItem(
                name="DATA_FEED",
                passed=False,
                detail=f"Data feed error: {exc}",
            )

    # ── Safe account fetch ────────────────────────────────────────────────────

    async def _safe_account_state(self) -> AccountState:
        from adapters.base import AccountState as _AS, AccountType as _AT

        try:
            return await self._broker.account_state()
        except Exception as exc:  # noqa: BLE001
            log.error("readiness.account_state_failed", error=str(exc))
            return _AS(
                equity=Decimal("0"),
                cash=Decimal("0"),
                buying_power=Decimal("0"),
                account_type=_AT.UNKNOWN,
                pdt_restricted=True,
            )


__all__ = ["ReadinessChecker"]
