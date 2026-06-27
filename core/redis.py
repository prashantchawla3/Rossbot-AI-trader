"""Redis connection factory — hot state / pub-sub (CLAUDE.md §3 architecture).

Backed by Upstash (hosted Redis, free tier) now that the local docker-compose Redis is archived.
Upstash forces TLS, so the URL uses the ``rediss://`` scheme; redis-py negotiates SSL from it.
RossBot is a long-running process, so the connection-based ``redis-py`` client is the right fit
(the HTTP ``upstash-redis`` client is for serverless/edge — not us).

Connection string (Upstash → database page → "Redis" / connect):
    rediss://default:<UPSTASH_PASSWORD>@<endpoint>.upstash.io:6379

verified: upstash.com/docs/redis/howto/connect-client (2026-06) — TLS always on (ssl=True);
verified: redis.readthedocs.io SSL examples — rediss:// URL enables TLS via from_url (2026-06).
"""

from __future__ import annotations

import os

import redis
from dotenv import load_dotenv

# Load .env so ROSSBOT_REDIS_URL is available in local dev (no Docker). No-op in CI/prod.
load_dotenv()

# Tuning for a long-running connection: detect dropped sockets and keep them warm.
_HEALTH_CHECK_INTERVAL_S = 30
_SOCKET_TIMEOUT_S = 10


def redis_url() -> str:
    """Resolve the Redis URL from env (fail-safe: explicit error if unset)."""
    url = os.environ.get("ROSSBOT_REDIS_URL")
    if not url:
        raise RuntimeError("ROSSBOT_REDIS_URL is not set (see .env.example)")
    return url


def make_redis_client(
    url: str | None = None, *, decode_responses: bool = True
) -> redis.Redis:
    """Create a redis-py client (TLS auto-enabled for Upstash ``rediss://`` URLs).

    ``decode_responses=True`` returns ``str`` (convenient for JSON/string caching); pass
    ``False`` if a caller needs raw ``bytes``. Connection pooling is handled by redis-py.
    """
    return redis.Redis.from_url(
        url or redis_url(),
        decode_responses=decode_responses,
        health_check_interval=_HEALTH_CHECK_INTERVAL_S,
        socket_timeout=_SOCKET_TIMEOUT_S,
        socket_keepalive=True,
    )


def ping(url: str | None = None) -> bool:
    """Fail-safe connectivity probe — True only if the server answers PING."""
    try:
        client = make_redis_client(url)
        return bool(client.ping())
    except Exception:  # noqa: BLE001 — any failure → not connected (fail closed)
        return False
