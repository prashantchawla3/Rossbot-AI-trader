"""Verify the Upstash Redis connection (local dev helper).

Usage:
    python scripts/check_redis.py

Loads .env, connects to ROSSBOT_REDIS_URL, and round-trips a key. Exit 0 on success.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from core.redis import make_redis_client  # noqa: E402 — after load_dotenv


def main() -> int:
    try:
        client = make_redis_client()
        client.set("rossbot:healthcheck", "ok", ex=60)
        value = client.get("rossbot:healthcheck")
    except Exception as exc:  # noqa: BLE001
        print(f"Redis connection FAILED: {exc}")
        print("Check ROSSBOT_REDIS_URL in .env (Upstash uses rediss://...:6379).")
        return 1
    print(f"Redis OK — round-trip value: {value!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
