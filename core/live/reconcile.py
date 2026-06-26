"""Position reconciliation — pure function comparing broker vs. internal state.

Called by LiveSession every RECONCILE_INTERVAL_S seconds. Pure and side-effect-free
so it can be tested without a live broker.

Discrepancy actions (taken by the caller, not here):
- broker_only   → GHOST: log + alert; do NOT trade the ghost; optionally add to tracking.
- internal_only → ORPHAN: our fill/close was missed; correct state by removing from _open.
- qty_mismatch  → STALE: our quantity tracking drifted; update from broker truth.

spec Phase 6 reconciliation / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

from core.live.models import ReconcileResult


def reconcile_positions(
    broker: dict[str, int],
    internal: dict[str, int],
) -> ReconcileResult:
    """Compare ``broker`` {symbol → qty} with ``internal`` {symbol → qty}.

    Returns a ``ReconcileResult`` describing every discrepancy class.
    The caller decides corrective action; this function is pure (no side effects).

    :param broker:   positions currently held at the broker (from get_broker_positions()).
    :param internal: positions tracked internally by LiveSession._open.
    """
    broker_syms = frozenset(broker)
    internal_syms = frozenset(internal)

    matched_syms = broker_syms & internal_syms
    broker_only = broker_syms - internal_syms
    internal_only = internal_syms - broker_syms

    # Qty mismatch: symbol present in both but quantity disagrees
    qty_mismatch = frozenset(
        sym for sym in matched_syms if broker[sym] != internal[sym]
    )

    # True-matched: present in both AND qty agrees
    matched = matched_syms - qty_mismatch

    return ReconcileResult(
        matched=matched,
        broker_only=broker_only,
        internal_only=internal_only,
        qty_mismatch=qty_mismatch,
    )


__all__ = ["reconcile_positions"]
