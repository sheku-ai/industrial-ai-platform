from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Response, status


class RuntimeWorkerHealthProvider(Protocol):
    def health_payload(self) -> dict[str, object]: ...


def build_runtime_worker_health_router(
    provider: RuntimeWorkerHealthProvider,
    *,
    prefix: str = "/internal/runtime-worker",
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["runtime-worker-health"])

    @router.get("/live")
    def liveness(response: Response) -> dict[str, object]:
        payload = dict(provider.health_payload())
        live = bool(payload.get("live", False))
        if not live:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "live" if live else "unavailable",
            "worker_id": payload.get("worker_id"),
            "live": live,
        }

    @router.get("/ready")
    def readiness(response: Response) -> dict[str, object]:
        payload = dict(provider.health_payload())
        ready = bool(payload.get("ready", False))
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if ready else "not_ready",
            "worker_id": payload.get("worker_id"),
            "ready": ready,
            "stop_requested": bool(payload.get("stop_requested", False)),
            "active": bool(payload.get("active", False)),
        }

    @router.get("/health")
    def health() -> dict[str, object]:
        return dict(provider.health_payload())

    return router
