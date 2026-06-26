"""Unit tests for the alerting service.  spec Phase 5."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from api.services.alert_service import AlertService, AlertSeverity


@pytest.fixture
def svc() -> AlertService:
    # Unset channels so tests don't actually send messages
    env = {k: v for k, v in os.environ.items() if k not in ("SLACK_WEBHOOK_URL", "ALERT_EMAIL_TO")}
    with patch.dict(os.environ, env, clear=True):
        return AlertService()


def run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAlertService:
    def test_init_no_channels(self, svc: AlertService) -> None:
        assert svc._slack_url is None
        assert svc._email_to == []

    def test_fire_no_channels_does_not_raise(self, svc: AlertService) -> None:
        # Should complete silently with no configured channels
        run(svc.fire(AlertSeverity.CRITICAL, "test_event", "test message"))

    def test_fire_slack_posts_to_webhook(self) -> None:
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://fake-slack/hook"}):
            svc = AlertService()

        posted: list[str] = []

        def fake_send(url: str, text: str, severity: AlertSeverity) -> None:
            posted.append(text)

        svc._send_slack_sync = fake_send  # type: ignore[assignment]

        run(svc.fire(AlertSeverity.WARN, "feed_gap", "quote feed stale"))

        assert len(posted) == 1
        assert "feed_gap" in posted[0]
        assert "quote feed stale" in posted[0]

    def test_fire_email_sends_message(self) -> None:
        with patch.dict(
            os.environ,
            {"ALERT_EMAIL_TO": "ops@example.com", "SMTP_HOST": "localhost"},
        ):
            svc = AlertService()

        subjects: list[str] = []

        def fake_send(subject: str, body: str) -> None:
            subjects.append(subject)

        svc._send_email_sync = fake_send  # type: ignore[assignment]

        run(svc.fire(AlertSeverity.CRITICAL, "kill_switch", "Manual halt"))

        assert len(subjects) == 1
        assert "kill_switch" in subjects[0]

    def test_severity_in_message_text(self) -> None:
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://x/hook"}):
            svc = AlertService()

        texts: list[str] = []
        svc._send_slack_sync = lambda u, t, s: texts.append(t)  # type: ignore[assignment]

        run(svc.fire(AlertSeverity.CRITICAL, "lockout", "Daily loss limit hit"))

        assert "CRITICAL" in texts[0]

    def test_slack_failure_does_not_raise(self) -> None:
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://invalid-host-xyz/hook"}):
            svc = AlertService()
        # Should not raise even when the network call fails
        run(svc.fire(AlertSeverity.WARN, "test", "message"))
