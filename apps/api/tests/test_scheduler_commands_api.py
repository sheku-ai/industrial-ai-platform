from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.authentication import require_api_access
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.security.resource_scope import ResourceScopeType
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_authenticated_api_boundary():
    app.dependency_overrides[require_api_access] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_api_access, None)
        app.dependency_overrides.pop(get_runtime_context, None)


def _context(permissions=()):
    return RuntimeRequestContext(
        scope_type=ResourceScopeType.ORGANIZATION.value,
        organization_id=uuid4(),
        actor_reference="scheduler-test",
        permissions=frozenset(permissions),
    )


def test_scheduler_run_command_route_is_registered() -> None:
    path = "/api/control-plane/scheduler/jobs/{job_id}/runs"
    assert path in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"][path]


def test_scheduler_run_command_requires_administer_permission() -> None:
    app.dependency_overrides[get_runtime_context] = lambda: _context()
    response = client.post(
        f"/api/control-plane/scheduler/jobs/{uuid4()}/runs",
        json={"idempotency_key": "test-run"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "scheduler administer permission is required"
