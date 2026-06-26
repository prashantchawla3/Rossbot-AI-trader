"""Alerting service — Slack webhook + SMTP email on risk events, lockouts, feed gaps.

spec Phase 5: "Alerting (Slack/email) on risk events, lockouts, disconnects, feed gaps."

Config via env vars (NOT the strategy config table — these are infra settings):
  SLACK_WEBHOOK_URL  - Slack incoming webhook URL; omit to disable Slack alerts.
  ALERT_EMAIL_TO     - comma-separated recipient addresses; omit to disable email.
  SMTP_HOST          - SMTP server hostname (default: localhost)
  SMTP_PORT          - SMTP port (default: 587)
  SMTP_USER          - SMTP username (optional)
  SMTP_PASSWORD      - SMTP password (optional)
  SMTP_FROM          - From address (default: rossbot@localhost)
  SMTP_TLS           - "true" (default) or "false"

Both channels are best-effort: a failure to deliver an alert does NOT stop trading.
"""

from __future__ import annotations

import asyncio
import email.message
import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alert")


class AlertSeverity(StrEnum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class AlertService:
    """Best-effort Slack + email alerting.

    All network I/O runs in a ``ThreadPoolExecutor`` so it never blocks
    the asyncio event loop (trading path must not be delayed by alert delivery).
    """

    def __init__(self) -> None:
        self._slack_url: str | None = os.environ.get("SLACK_WEBHOOK_URL")
        self._email_to: list[str] = [
            a.strip()
            for a in os.environ.get("ALERT_EMAIL_TO", "").split(",")
            if a.strip()
        ]
        self._smtp_host = os.environ.get("SMTP_HOST", "localhost")
        self._smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self._smtp_user = os.environ.get("SMTP_USER")
        self._smtp_pass = os.environ.get("SMTP_PASSWORD")
        self._smtp_from = os.environ.get("SMTP_FROM", "rossbot@localhost")
        self._smtp_tls = os.environ.get("SMTP_TLS", "true").lower() != "false"

        _configured = bool(self._slack_url or self._email_to)
        log.info(
            "alert_service.init slack=%s email_count=%d",
            bool(self._slack_url),
            len(self._email_to),
        )
        if not _configured:
            log.warning(
                "alert_service: no channels configured "
                "(set SLACK_WEBHOOK_URL or ALERT_EMAIL_TO)"
            )

    async def fire(
        self,
        severity: AlertSeverity,
        event_type: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        """Fire an alert on all configured channels.  Best-effort; never raises."""
        log.info("alert.fire severity=%s type=%s msg=%s", severity, event_type, message)
        loop = asyncio.get_running_loop()

        full_message = f"[RossBot/{severity.upper()}] {event_type}: {message}"
        if detail:
            full_message += f"\n{detail}"

        tasks: list[Any] = []
        if self._slack_url:
            tasks.append(
                loop.run_in_executor(
                    _EXECUTOR,
                    self._send_slack_sync,
                    self._slack_url,
                    full_message,
                    severity,
                )
            )
        if self._email_to:
            tasks.append(
                loop.run_in_executor(
                    _EXECUTOR,
                    self._send_email_sync,
                    f"RossBot {severity.upper()}: {event_type}",
                    full_message,
                )
            )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Synchronous channel implementations (run in thread pool) ──────────────

    def _send_slack_sync(
        self, webhook_url: str, text: str, severity: AlertSeverity
    ) -> None:
        """POST to a Slack incoming webhook URL.  Runs in a thread."""
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                status = resp.status
                if status != 200:
                    log.warning("alert.slack_bad_status status=%d", status)
        except urllib.error.URLError as exc:
            log.error("alert.slack_failed exc=%s", exc)
        except Exception:  # noqa: BLE001
            log.exception("alert.slack_unexpected_error")

    def _send_email_sync(self, subject: str, body: str) -> None:
        """Send an email via SMTP.  Runs in a thread."""
        msg = email.message.EmailMessage()
        msg["From"] = self._smtp_from
        msg["To"] = ", ".join(self._email_to)
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            if self._smtp_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as srv:
                    srv.starttls(context=context)
                    if self._smtp_user and self._smtp_pass:
                        srv.login(self._smtp_user, self._smtp_pass)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as srv:
                    if self._smtp_user and self._smtp_pass:
                        srv.login(self._smtp_user, self._smtp_pass)
                    srv.send_message(msg)
            log.info("alert.email_sent to=%s", self._email_to)
        except smtplib.SMTPException as exc:
            log.error("alert.email_smtp_error exc=%s", exc)
        except OSError as exc:
            log.error("alert.email_connect_error exc=%s", exc)
        except Exception:  # noqa: BLE001
            log.exception("alert.email_unexpected_error")
