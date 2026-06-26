"""Tests for reconcile_positions() pure function (Phase 6).

spec Phase 6 reconciliation / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import pytest

from core.live.reconcile import reconcile_positions


def test_reconcile_all_matched():
    broker = {"TSLA": 100, "NVDA": 200}
    internal = {"TSLA": 100, "NVDA": 200}

    result = reconcile_positions(broker, internal)

    assert result.clean
    assert result.matched == frozenset({"TSLA", "NVDA"})
    assert not result.broker_only
    assert not result.internal_only
    assert not result.qty_mismatch


def test_reconcile_broker_only():
    """Broker has AAPL which we're not tracking → ghost position."""
    broker = {"TSLA": 100, "AAPL": 500}
    internal = {"TSLA": 100}

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.broker_only == frozenset({"AAPL"})
    assert not result.internal_only
    assert result.matched == frozenset({"TSLA"})


def test_reconcile_internal_only():
    """We track GME but broker doesn't have it → orphan state."""
    broker = {"TSLA": 100}
    internal = {"TSLA": 100, "GME": 250}

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.internal_only == frozenset({"GME"})
    assert not result.broker_only


def test_reconcile_qty_mismatch():
    """Both have TSLA but quantities differ → qty_mismatch."""
    broker = {"TSLA": 100}
    internal = {"TSLA": 200}

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.qty_mismatch == frozenset({"TSLA"})
    assert not result.matched  # mismatch → NOT in matched


def test_reconcile_multiple_discrepancy_classes():
    """All three discrepancy classes present simultaneously."""
    broker = {"TSLA": 100, "GHOST": 50}
    internal = {"TSLA": 200, "ORPHAN": 75}  # TSLA qty differs; GHOST=broker-only; ORPHAN=internal-only

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.qty_mismatch == frozenset({"TSLA"})
    assert result.broker_only == frozenset({"GHOST"})
    assert result.internal_only == frozenset({"ORPHAN"})
    assert not result.matched  # TSLA qty mismatch → not in matched


def test_reconcile_empty_both():
    result = reconcile_positions({}, {})
    assert result.clean
    assert not result.matched
    assert not result.broker_only
    assert not result.internal_only
    assert not result.qty_mismatch


def test_reconcile_broker_empty_internal_has_positions():
    """We think we have positions but broker is empty → all orphans."""
    broker = {}
    internal = {"AAPL": 100, "TSLA": 50}

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.internal_only == frozenset({"AAPL", "TSLA"})
    assert not result.broker_only


def test_reconcile_internal_empty_broker_has_positions():
    """Broker has positions we're not tracking → all ghosts."""
    broker = {"SPY": 10, "QQQ": 5}
    internal = {}

    result = reconcile_positions(broker, internal)

    assert not result.clean
    assert result.broker_only == frozenset({"SPY", "QQQ"})
    assert not result.internal_only


def test_reconcile_summary_clean():
    result = reconcile_positions({"TSLA": 100}, {"TSLA": 100})
    assert "OK" in result.summary()
    assert "1 position" in result.summary()


def test_reconcile_summary_discrepancy():
    result = reconcile_positions({"GHOST": 50}, {"ORPHAN": 75})
    summary = result.summary()
    assert "DISCREPANCY" in summary
    assert "broker-only" in summary
    assert "internal-only" in summary
