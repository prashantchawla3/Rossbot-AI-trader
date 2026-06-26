"""Minimal FastAPI app (Phase 0): liveness only. No trading endpoints exist yet.

verified: fastapi.tiangolo.com (FastAPI 0.138.x, 2026-06).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from core.logging import configure_logging
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


app = FastAPI(title="RossBot", version="0.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe. Does not assert trade-readiness (that is the risk gate's job)."""
    return {"status": "ok", "service": "rossbot", "phase": 0}
