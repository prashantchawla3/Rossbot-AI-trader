"""API key authentication dependency for the dashboard.

spec Phase 5 — dashboard exposes kill-switch + pause only; auth guards
every mutating endpoint (U11: no mid-session parameter editing).
Key is read from env var DASHBOARD_API_KEY; missing key = all controls blocked.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_API_KEY: str | None = os.environ.get("DASHBOARD_API_KEY")


async def require_api_key(key: str | None = Security(_KEY_HEADER)) -> None:
    """FastAPI dependency — raises 403 if key is absent or wrong."""
    expected = _API_KEY
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_API_KEY not configured",
        )
    if key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header",
        )
