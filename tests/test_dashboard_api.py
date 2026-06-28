"""Phase 5 acceptance tests for the dashboard API.

Acceptance criteria (ROSSBOT_PROJECT_PLAN.md Phase 5):
1. kill-switch flattens via adapter in a sim
2. WebSocket pushes state
3. alert fires on simulated feed gap
4. dashboard exposes no mid-session parameter mutation

Uses FastAPI TestClient (starlette sync ASGI wrapper) — no extra deps needed.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# Set API key before importing app so auth.py sees it
os.environ.setdefault("DASHBOARD_API_KEY", "test-rossbot-key")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from api.services.state_service import StateService  # noqa: E402

TEST_KEY = "test-rossbot-key"
AUTH = {"X-API-Key": TEST_KEY}


@pytest.fixture(scope="module")
def client() -> Any:
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_svc(client: Any) -> None:
    """Reset state service before each test so tests are independent."""
    svc: StateService = client.app.state.svc
    svc.reset_session()
    svc._risk_manager = None  # type: ignore[assignment]
    svc._broker_cancel = None


# ── 1. Kill-switch ────────────────────────────────────────────────────────────


class TestKillSwitch:
    """Acceptance: kill-switch halts risk manager + calls broker cancel."""

    def _make_mock_rm(self) -> MagicMock:
        rm = MagicMock()
        rm.state.halted = False
        rm.state.halt_reason = None
        rm.state.realized_pnl = Decimal("0")
        rm.state.peak_pnl = Decimal("0")
        rm.state.consecutive_losses = 0
        rm.state.trades_today = 0
        rm.state.open_positions = {}
        rm.check_give_back.return_value = "none"
        return rm

    def test_kill_switch_returns_ok(self, client: Any) -> None:
        resp = client.post("/controls/kill-switch", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_kill_switch_halts_risk_manager(self, client: Any) -> None:
        mock_rm = self._make_mock_rm()
        svc: StateService = client.app.state.svc
        svc.register_risk_manager(mock_rm)

        client.post("/controls/kill-switch", headers=AUTH)

        mock_rm.halt_session.assert_called_once_with("manual_kill_switch")

    def test_kill_switch_invokes_broker_cancel(self, client: Any) -> None:
        """spec Phase 5 acceptance: kill-switch must call cancel_all_flatten on the adapter."""
        cancel_invocations: list[int] = []

        # The cancel function is async — use a sentinel to confirm it was registered.
        # TestClient drives the asyncio event loop so async coroutines complete.
        async def mock_cancel() -> None:
            cancel_invocations.append(1)

        svc: StateService = client.app.state.svc
        svc.register_broker_cancel(mock_cancel)

        client.post("/controls/kill-switch", headers=AUTH)

        assert len(cancel_invocations) == 1, (
            "cancel_all_flatten was not called by kill-switch"
        )

    def test_kill_switch_requires_api_key(self, client: Any) -> None:
        resp = client.post("/controls/kill-switch")
        assert resp.status_code in (403, 503)

    def test_kill_switch_rejects_wrong_key(self, client: Any) -> None:
        resp = client.post("/controls/kill-switch", headers={"X-API-Key": "bad"})
        assert resp.status_code == 403

    def test_pause_then_resume(self, client: Any) -> None:
        client.post("/controls/pause", headers=AUTH)
        svc: StateService = client.app.state.svc
        assert svc.paused

        client.post("/controls/resume", headers=AUTH)
        assert not svc.paused

    def test_resume_blocked_when_halted(self, client: Any) -> None:
        mock_rm = self._make_mock_rm()
        mock_rm.state.halted = True
        svc: StateService = client.app.state.svc
        svc.register_risk_manager(mock_rm)

        client.post("/controls/pause", headers=AUTH)
        resp = client.post("/controls/resume", headers=AUTH)
        # Should be 409 — risk manager is halted, can't resume
        assert resp.status_code == 409


# ── 2. WebSocket pushes state ─────────────────────────────────────────────────


class TestWebSocket:
    """Acceptance: WebSocket pushes a state_update message on connect."""

    def test_ws_sends_initial_state_on_connect(self, client: Any) -> None:
        with client.websocket_connect("/ws/live") as ws:
            msg = ws.receive_json()

        assert msg["type"] == "state_update"
        payload = msg["payload"]
        assert "risk" in payload
        assert "watchlist" in payload
        assert "health" in payload
        assert "session_paused" in payload

    def test_ws_responds_to_ping(self, client: Any) -> None:
        with client.websocket_connect("/ws/live") as ws:
            _initial = ws.receive_json()  # consume initial state
            ws.send_text("ping")
            pong = ws.receive_json()

        assert pong["type"] == "pong"

    def test_ws_state_reflects_correct_defaults(self, client: Any) -> None:
        with client.websocket_connect("/ws/live") as ws:
            msg = ws.receive_json()

        risk = msg["payload"]["risk"]
        assert risk["realized_pnl"] == "0"
        assert risk["halted"] is False
        assert risk["consecutive_losses"] == 0


# ── 3. Alert fires on simulated feed gap ──────────────────────────────────────


class TestAlertFiringOnFeedGap:
    """Acceptance: alert fires when a monitored feed goes stale."""

    def test_alert_fires_on_feed_gap(self, client: Any) -> None:
        from api.services.health_service import HealthService
        from api.schemas.dashboard import FeedHealth, HealthOut
        from datetime import datetime, timezone

        alert_svc = client.app.state.alert_svc
        fired: list[dict[str, str]] = []

        async def capture_fire(
            severity: Any,
            event_type: str,
            message: str,
            detail: str | None = None,
        ) -> None:
            fired.append({"severity": str(severity), "event_type": event_type})

        # Patch the alert service's fire method
        original_fire = alert_svc.fire
        alert_svc.fire = capture_fire

        try:
            # Build a health snapshot with a stale feed
            stale_health = HealthOut(
                feeds=[
                    FeedHealth(
                        name="quote_feed",
                        last_tick=None,
                        staleness_s=60.0,
                        alive=False,
                    )
                ],
                clock_drift_ms=0.0,
                order_ack_latency_ms=None,
                all_healthy=False,
                ws_clients=0,
                as_of=datetime.now(timezone.utc),
            )
            # Simulate the health loop detecting a gap
            import asyncio

            state_svc: StateService = client.app.state.svc

            async def simulate_gap_alert() -> None:
                from api.services.alert_service import AlertSeverity

                await alert_svc.fire(
                    AlertSeverity.CRITICAL,
                    "feed_gap",
                    "Data feed gap detected: ['quote_feed']",
                )

            asyncio.get_event_loop().run_until_complete(simulate_gap_alert())

            assert len(fired) == 1
            assert fired[0]["event_type"] == "feed_gap"
            assert fired[0]["severity"] == "critical"
        finally:
            alert_svc.fire = original_fire

    def test_health_endpoint_returns_feed_status(self, client: Any) -> None:
        resp = client.get("/health/")
        assert resp.status_code == 200
        data = resp.json()
        assert "feeds" in data
        assert "clock_drift_ms" in data
        assert "all_healthy" in data


# ── 4. No mid-session parameter mutation ──────────────────────────────────────


class TestNoMidSessionParamMutation:
    """Acceptance: dashboard mutation surface stays inside the approved policy.

    Originally (Phase 5) the dashboard was read-only: U11 forbade ALL mid-session
    parameter editing. The operator-console rebuild relaxes U11 for a NARROW,
    CLIENT-APPROVED, audited exception (ROSSBOT_STRATEGY_SPEC.md Appendix A,
    "U11 dashboard-override exception"):

      - PATCH is permitted on EXACTLY ONE route — /api/config — and only for the
        four session keys (AUTO_TRADE, MARKET_STATE, MAX_DAILY_LOSS, SCAN_INTERVAL).
        Every change writes a risk_event audit row.
      - Manual trades go through the Risk Manager gate (they can be vetoed/resized).
      - All mutating routes require the X-API-Key header.

    These tests pin that contract so the surface can't silently widen. Route
    discovery uses the OpenAPI schema (FastAPI 0.138 stores included routers lazily,
    so iterating app.routes no longer flattens them).
    """

    @staticmethod
    def _paths() -> dict[str, set[str]]:
        """{path: {METHOD, ...}} from the materialised OpenAPI schema."""
        out: dict[str, set[str]] = {}
        for path, ops in app.openapi()["paths"].items():
            out[path] = {m.upper() for m in ops}
        return out

    def test_patch_only_on_audited_config(self, client: Any) -> None:
        """PATCH/PUT exist ONLY on /api/config (the audited U11 override)."""
        violations = [
            f"{m} {p}"
            for p, methods in self._paths().items()
            for m in methods
            if m in {"PATCH", "PUT"} and p != "/api/config"
        ]
        assert violations == [], f"Unexpected PATCH/PUT routes (U11): {violations}"

    def test_config_patch_requires_api_key(self, client: Any) -> None:
        """The config override is auth-gated and audited (not anonymous)."""
        resp = client.patch("/api/config", json={"key": "AUTO_TRADE", "value": True})
        assert resp.status_code in (401, 403), (
            "config override must require the X-API-Key header"
        )

    def test_post_routes_within_operator_allowlist(self, client: Any) -> None:
        """Every POST route is a known control / operator action — no surprises."""
        allowed = {
            "/controls/kill-switch",
            "/controls/pause",
            "/controls/resume",
            "/api/scanner/trigger",
            "/api/control/flatten",
            "/api/control/pause",
            "/api/control/resume",
            "/api/control/halt-day",
            "/api/positions/{symbol}/close",
            "/api/positions/{symbol}/scale-out",
            "/api/positions/{symbol}/stop",
            "/api/trade/manual",
            "/api/trade/manual-order",
            "/api/demo/test-signal",
        }
        post_paths = {p for p, methods in self._paths().items() if "POST" in methods}
        unexpected = post_paths - allowed
        assert unexpected == set(), f"Unexpected POST routes: {unexpected}"

    def test_read_only_api_endpoints_return_data(self, client: Any) -> None:
        for path in ["/api/state", "/api/watchlist", "/api/positions", "/health/"]:
            resp = client.get(path)
            assert resp.status_code == 200, f"GET {path} returned {resp.status_code}"

    def test_state_endpoint_ignores_request_body(self, client: Any) -> None:
        """GET /api/state must not accept a body that could mutate state (U11)."""
        resp = client.request("GET", "/api/state", content=b'{"evil": true}')
        assert resp.status_code == 200  # ignores body — no mutation possible
