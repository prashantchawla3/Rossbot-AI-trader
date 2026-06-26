"""Structured JSON logging (structlog).

STANDING RULES B / plan Phase 0: structured logging, secrets via env (never logged).
Every audit-worthy event in later phases (orders, vetoes) is also persisted to the DB;
this logger is the operational stream, the DB ledger is the legal record.

verified: www.structlog.org configuration API (structlog 26.x, 2026-06).
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure process-wide structlog. Idempotent; call once at startup.

    ``json_output=True`` emits one JSON object per line (production / CI).
    ``json_output=False`` emits a colorized console renderer (local dev).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
