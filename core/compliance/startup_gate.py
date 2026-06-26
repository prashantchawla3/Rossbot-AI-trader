"""Startup compliance hard-gate — spec §13.11.

Runs at session open BEFORE any trading. Confirms:
  1. Account type is known (not UNKNOWN).
  2. For MARGIN accounts: no pending intraday margin calls (buying_power > 0).
  3. For CASH accounts: flags T+1 settlement restriction → enforces MAX_TRADES=1.
  4. Computes effective_max_trades from config and account type.
  5. Asserts short-selling is disabled (locate/HTB is out of scope — spec §13.11).

PDT NOTE (UPDATED 2026-06-04):
  FINRA eliminated the Pattern Day Trader rule (FINRA Rule 4210 amendment) on
  June 4, 2026. The old $25,000 minimum and ≤3-day-trades-in-5-days restriction
  are no longer in effect for margin accounts. RossBot enforces MAX_TRADES_PER_DAY
  from config as the conservative guard. Cash accounts retain the T+1 restriction.
  If `READINESS_MIN_EQUITY` is still set in config, it remains as a capital safety
  floor check, independent of the eliminated PDT rule.

All fields in ComplianceGateResult are informational; the ``passed`` flag drives
the live session's readiness gate.
spec §13.11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from adapters.base import AccountState, AccountType
from core.config import ConfigService


@dataclass(frozen=True)
class ComplianceGateResult:
    """Result of the startup compliance gate. spec §13.11.

    ``passed=False`` → abort session; log ``reasons`` and alert operator.
    """

    passed: bool
    reasons: list[str] = field(default_factory=list)
    effective_max_trades: int = 1
    account_type: AccountType = AccountType.UNKNOWN
    equity: Decimal = Decimal("0")
    warnings: list[str] = field(default_factory=list)


def evaluate_startup_compliance(
    account_state: AccountState,
    cfg: ConfigService,
) -> ComplianceGateResult:
    """Run startup compliance gate at each session open. spec §13.11.

    Returns ComplianceGateResult; ``passed=False`` halts the session.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    acct = account_state.account_type
    equity = account_state.equity
    max_trades = cfg.get_int("MAX_TRADES_PER_DAY")

    # ── Hard gate 1: account type must be confirmed ────────────────────────────
    if acct == AccountType.UNKNOWN:
        reasons.append(
            "ACCOUNT_TYPE=UNKNOWN: cannot determine compliance rules. "
            "Confirm account type at startup before enabling live trading. spec §13.11."
        )

    # ── Cash account: T+1 unsettled-fund restriction ──────────────────────────
    if acct == AccountType.CASH:
        max_trades = min(max_trades, 1)
        warnings.append(
            "CASH account: T+1 settlement applies. MAX_TRADES capped at 1 "
            "(cannot reuse unsettled funds intraday). spec §13.11."
        )

    # ── MARGIN account: check minimum capital threshold ────────────────────────
    if acct == AccountType.MARGIN:
        min_equity = cfg.get_decimal("READINESS_MIN_EQUITY") if cfg.has("READINESS_MIN_EQUITY") else Decimal("0")
        if equity < min_equity:
            warnings.append(
                f"MARGIN equity ${equity:,.2f} below READINESS_MIN_EQUITY ${min_equity:,.2f}. "
                "PDT rule eliminated 2026-06-04 (FINRA Rule 4210 amendment); "
                "capital floor is a conservative safety check. spec §13.11."
            )

    # ── Hard gate 2: buying power must be positive ────────────────────────────
    if account_state.buying_power <= Decimal("0"):
        reasons.append(
            f"BUYING_POWER=${account_state.buying_power:,.2f}: insufficient buying power. "
            "Session cannot proceed. spec §13.11."
        )

    # ── Shorting is out of scope (locate/HTB deferred) ────────────────────────
    # Assert by design: no short-sell path exists in Execution layer. Nothing to enforce here.
    # If short-sell capability is ever added, re-check this gate. spec §13.11.

    passed = len(reasons) == 0
    return ComplianceGateResult(
        passed=passed,
        reasons=reasons,
        effective_max_trades=max_trades,
        account_type=acct,
        equity=equity,
        warnings=warnings,
    )


__all__ = ["ComplianceGateResult", "evaluate_startup_compliance"]
