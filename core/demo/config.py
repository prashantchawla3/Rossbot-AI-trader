"""Demo runtime configuration — read from environment with cautious defaults.

These are DEMO operational knobs (Alpaca creds, loop cadence, paper limits). The
*strategy* thresholds (Five Pillars, spread band, retrace, etc.) still come from
``core.config.ConfigService`` — see ``DemoEngine``. Keeping demo knobs in env means
the demo runs with NO database and NO Redis dependency.

spec: ROSSBOT_PROJECT_PLAN.md Phase 6 (paper) / CLAUDE.md §2 (typed config).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _env(key: str, default: str) -> str:
    val = os.environ.get(key)
    return val if val is not None and val != "" else default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_dec(key: str, default: str) -> Decimal:
    try:
        return Decimal(_env(key, default))
    except Exception:  # noqa: BLE001
        return Decimal(default)


@dataclass(frozen=True)
class DemoConfig:
    """Snapshot of demo runtime settings, materialised once at engine start."""

    # ── Broker / data credentials (Alpaca paper) ──────────────────────────────
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str
    alpaca_data_feed: str          # "iex" (free) or "sip" (paid)

    # ── Behaviour flags ───────────────────────────────────────────────────────
    environment: str               # paper | sim | live (demo → paper)
    auto_trade: bool               # actually submit paper orders vs. signal-only
    e6_enabled: bool               # L2 support gate — BYPASSED for demo (False)
    market_state: str              # forced HOT for the demo
    demo_replay_mode: bool         # replay synthetic activity when market is closed

    # ── Paper risk limits (demo) ──────────────────────────────────────────────
    max_daily_loss: Decimal        # USD; shutdown trading loop below -this
    max_position_size: int         # share cap per order
    per_trade_risk: Decimal        # USD risk budget per trade (sizing)
    hard_stop_time: str            # "HH:MM" ET — no new entries after this

    # ── Loop cadence (seconds) ────────────────────────────────────────────────
    scan_interval_s: int
    strategy_interval_s: int
    exit_interval_s: int

    # ── Universe ──────────────────────────────────────────────────────────────
    snapshot_batch: int            # symbols per Alpaca snapshot request

    @property
    def has_credentials(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def paper(self) -> bool:
        return self.environment.lower() != "live"

    @classmethod
    def from_env(cls) -> "DemoConfig":
        return cls(
            alpaca_api_key=_env("ALPACA_API_KEY", ""),
            alpaca_secret_key=_env("ALPACA_SECRET_KEY", ""),
            alpaca_base_url=_env("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            # IEX is the free Alpaca feed; SIP needs a paid sub. Demo defaults IEX.
            alpaca_data_feed=_env("ALPACA_DATA_FEED", "iex").lower(),
            environment=_env("ENVIRONMENT", _env("ROSSBOT_ENV", "paper")),
            auto_trade=_env_bool("AUTO_TRADE", True),
            e6_enabled=_env_bool("E6_ENABLED", False),
            market_state=_env("MARKET_STATE", "HOT").upper(),
            demo_replay_mode=_env_bool("DEMO_REPLAY_MODE", True),
            max_daily_loss=_env_dec("MAX_DAILY_LOSS", "500"),
            max_position_size=_env_int("MAX_POSITION_SIZE", 5000),
            per_trade_risk=_env_dec("PER_TRADE_RISK", "1000"),
            hard_stop_time=_env("HARD_STOP_TIME", "11:00"),
            scan_interval_s=_env_int("SCAN_INTERVAL_S", 60),
            strategy_interval_s=_env_int("STRATEGY_INTERVAL_S", 30),
            exit_interval_s=_env_int("EXIT_INTERVAL_S", 5),
            snapshot_batch=_env_int("SNAPSHOT_BATCH", 100),
        )
