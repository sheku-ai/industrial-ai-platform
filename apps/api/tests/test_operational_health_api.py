from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.dependencies.authentication import (
    get_optional_authenticated_principal,
    require_api_access,
)
from app.api.dependencies.operational_health import get_operational_health_service
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.security.resource_scope import ResourceScopeType
from main import app


class _FakeHealthService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.session = SimpleNamespace(rollback=lambda: None)

    def get_snapshot(self, organization_id):
        if self.fail:
            raise OperationalError("health", {}, Exception("database unavailable"))
        now = datetime.now(UTC)
        return {
            "summary": {
                "organization_id": organization_id,
                "overall_status": "healthy",
                "active_issues": 0,
                "calculated_at": now,
            },
            "scheduler": {
                "enabled_jobs": 0,
                "disabled_jobs": 0,
                "enabled_schedules": 0,
                "overdue_schedules": 0,
                "schedules_without_next_run": 0,
                "pending_runs": 0,
                "active_runs": 0,
                "failed_runs": 0,
                "oldest_pending_run_at": None,
                "expired_claims": 0,
                "latest_success_at": None,
                "latest_failure_at": None,
            },
            "runtime": {
                "pending_executions": 0,
                "running_executions": 0,
                "retryable_executions": 0,
                "failed_executions": 0,
                "dead_letter_executions": 0,
                "cancelled_executions": 0,
                "oldest_non_terminal_execution_at": None,
                "expired_leases": 0,
                "stale_attempts": 0,
            },
            "artifact_publications": {
                "reserved": 0,
                "publishing": 0,
                "published": 0,
                "verified": 0,
                "missing": 0,
                "checksum_conflict": 0,
                "failed": 0,
                "oldest_unverified_publication_at": None,
            },
            "reconciliation": {
                "candidate_count": 0,
                "oldest_candidate_at": None,
                "missing_candidates": 0,
                "checksum_conflict_candidates": 0,
                "last_manual_run_at": None,
                "last_successful_run_at": None,
                "last_failed_run_at": None,
            },
            "freshness": {
                "calculated_at": now,
                "data_max_timestamp": None,
                "age_seconds": None,
                "is_stale": False,
            },
        }


@pytest.fixture(autouse=True)
def override_health_service():
    app.dependency_overrides[get_operational_health_service] = lambda: _FakeHealthService()
    app.dependency_overrides[get_optional_authenticated_principal] = lambda: None
    app.dependency_overrides[require_api_access] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_operational_health_service, None)
        app.dependency_overrides.pop(get_optional_authenticated_principal, None)
        app.dependency_overrides.pop(get_runtime_context, None)
        app.dependency_overrides.pop(require_api_access, None)


client = TestClient(app)


def _context(organization_id, permissions=()):
    return RuntimeRequestContext(
        scope_type=ResourceScopeType.ORGANIZATION.value,
        organization_id=organization_id,
        actor_reference="test-operator",
        permissions=frozenset(permissions),
    )


def test_health_route_is_registered() -> None:
    assert "/api/control-plane/health" in app.openapi()["paths"]
    assert "get" in app.openapi()["paths"]["/api/control-plane/health"]


def test_health_requires_organization_context() -> None:
    response = client.get("/api/control-plane/health")
    assert response.status_code == 401


def test_health_requires_read_permission() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id)

    response = client.get("/api/control-plane/health")

    assert response.status_code == 403
    assert response.json()["detail"] == "operational health read permission is required"


def test_health_returns_stable_snapshot_contract() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.health:read"},
    )

    response = client.get("/api/control-plane/health")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["organization_id"] == str(organization_id)
    assert body["summary"]["overall_status"] == "healthy"
    assert body["scheduler"]["enabled_schedules"] == 0
    assert body["scheduler"]["latest_success_at"] is None
    assert body["issues"] == []
    assert set(body) == {
        "summary",
        "scheduler",
        "issues",
        "runtime",
        "artifact_publications",
        "reconciliation",
        "freshness",
    }


def test_health_returns_503_when_database_query_fails() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.health:read"},
    )
    app.dependency_overrides[get_operational_health_service] = lambda: _FakeHealthService(fail=True)

    response = client.get("/api/control-plane/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "operational health data is unavailable"
