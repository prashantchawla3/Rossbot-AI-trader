"""Health check endpoints.  spec Phase 5."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas.dashboard import HealthOut
from api.services.health_service import HealthService

router = APIRouter(prefix="/health", tags=["health"])


def _hsvc(request: Request) -> HealthService:
    return request.app.state.health_svc  # type: ignore[no-any-return]


@router.get("/", response_model=HealthOut)
async def health_detail(request: Request) -> HealthOut:
    """Detailed health snapshot: feed liveness, clock drift, order-ack latency."""
    return _hsvc(request).build_health_snapshot()


@router.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    """Kubernetes-style readiness probe — returns 200 only if all feeds are alive."""
    snap = _hsvc(request).build_health_snapshot()
    if snap.all_healthy:
        return {"ready": True}
    from fastapi import HTTPException

    raise HTTPException(
        status_code=503,
        detail={"ready": False, "feeds": [f.model_dump(mode="json") for f in snap.feeds]},
    )
