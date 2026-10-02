from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.authentication import (
    get_optional_authenticated_principal,
    require_api_access,
)
from app.api.dependencies.reconciliation import get_reconciliation_batch_service
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.security.resource_scope import ResourceScopeType
from main import app


class _FakeBatchService:
    def run(self, organization_id, *, limit, statuses=None, cursor=None, dry_run=False):
        return SimpleNamespace(
            scanned=1,
            processed=1,
            changed=1,
            verified=1,
            missing=0,
            checksum_conflict=0,
            unchanged=0,
            failed=0,
            next_cursor=None,
            items=(
                SimpleNamespace(
                    source_publication_id=uuid4(),
                    resulting_publication_id=None if dry_run else uuid4(),
                    outcome="verified",
                    changed=True,
                    error_code=None,
                ),
            ),
        )


@pytest.fixture(autouse=True)
def override_dependencies():
    session = MagicMock()

    def _get_test_db():
        yield session

    app.dependency_overrides[get_reconciliation_batch_service] = lambda: _FakeBatchService()
    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_optional_authenticated_principal] = lambda: None
    app.dependency_overrides[require_api_access] = lambda: None
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_reconciliation_batch_service, None)
        app.dependency_overrides.pop(get_db, None)
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


def test_reconciliation_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/control-plane/reconciliation/artifacts/preview" in paths
    assert "/api/control-plane/reconciliation/artifacts/run" in paths


def test_preview_requires_organization_context() -> None:
    response = client.post(
        "/api/control-plane/reconciliation/artifacts/preview",
        json={"limit": 10},
    )

    assert response.status_code == 401


def test_preview_requires_read_permission() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id)

    response = client.post(
        "/api/control-plane/reconciliation/artifacts/preview",
        json={"limit": 10},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "reconciliation read permission is required"


def test_preview_accepts_read_permission() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.reconciliation:read"},
    )

    response = client.post(
        "/api/control-plane/reconciliation/artifacts/preview",
        json={"limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "preview"
    assert response.json()["changed"] == 1


def test_run_requires_administration_permission() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.reconciliation:read"},
    )

    response = client.post(
        "/api/control-plane/reconciliation/artifacts/run",
        json={"limit": 10},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "reconciliation administration permission is required"


def test_run_accepts_administration_permission(override_dependencies) -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.reconciliation:administer"},
    )

    response = client.post(
        "/api/control-plane/reconciliation/artifacts/run",
        json={"limit": 10, "correlation_id": "test-run-001"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "run"
    assert response.json()["processed"] == 1
    override_dependencies.add.assert_called_once()
    override_dependencies.commit.assert_called_once()


def test_limit_is_bounded_by_schema() -> None:
    organization_id = uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id,
        {"control_plane.reconciliation:read"},
    )

    response = client.post(
        "/api/control-plane/reconciliation/artifacts/preview",
        json={"limit": 101},
    )

    assert response.status_code == 422
