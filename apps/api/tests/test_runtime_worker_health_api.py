from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.runtime_worker_health import build_runtime_worker_health_router


class HealthProviderStub:
    def __init__(self, payload):
        self.payload = payload

    def health_payload(self):
        return dict(self.payload)


def build_client(payload):
    app = FastAPI()
    app.include_router(build_runtime_worker_health_router(HealthProviderStub(payload)))
    return TestClient(app)


def test_live_and_ready_endpoints_return_200_when_available():
    client = build_client(
        {
            "worker_id": "worker-1",
            "live": True,
            "ready": True,
            "stop_requested": False,
            "active": False,
            "cycles_total": 3,
        }
    )

    live = client.get("/internal/runtime-worker/live")
    ready = client.get("/internal/runtime-worker/ready")
    health = client.get("/internal/runtime-worker/health")

    assert live.status_code == 200
    assert live.json() == {"status": "live", "worker_id": "worker-1", "live": True}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert health.status_code == 200
    assert health.json()["cycles_total"] == 3


def test_readiness_returns_503_after_stop_request():
    client = build_client(
        {
            "worker_id": "worker-1",
            "live": True,
            "ready": False,
            "stop_requested": True,
            "active": False,
        }
    )

    response = client.get("/internal/runtime-worker/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["stop_requested"] is True


def test_liveness_returns_503_when_provider_reports_not_live():
    client = build_client(
        {
            "worker_id": "worker-1",
            "live": False,
            "ready": False,
            "stop_requested": False,
            "active": False,
        }
    )

    response = client.get("/internal/runtime-worker/live")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
