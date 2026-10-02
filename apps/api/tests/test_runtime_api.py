from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.identity.db import get_identity_db
from main import app


@pytest.fixture(autouse=True)
def override_database_dependency():
    session = MagicMock()

    def _get_test_db():
        yield session

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_identity_db] = lambda: iter((object(),))
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_identity_db, None)


client = TestClient(app)


def test_runtime_api_routes_are_registered_separately_from_ai_runtime() -> None:
    paths = app.openapi()["paths"]

    assert "/api/runtime/executions" in paths
    assert "/api/runtime/executions/{execution_id}" in paths
    assert "/api/runtime/executions/{execution_id}/attempts" in paths
    assert "/api/runtime/executions/{execution_id}/events" in paths
    assert "/api/runtime/executions/{execution_id}/artifacts" in paths
    assert "/api/runtime/executions/{execution_id}/cancel" in paths
    assert "/api/runtime/executions/{execution_id}/retry" in paths
    assert "/api/ai/runtime/status" in paths


def test_create_schema_does_not_accept_organization_id() -> None:
    schema = app.openapi()["components"]["schemas"]["RuntimeExecutionCreate"]

    assert "organization_id" not in schema["properties"]
    assert "execution_type" in schema["required"]
    assert "subject_id" in schema["required"]
    assert "idempotency_key" in schema["required"]


def test_runtime_api_requires_authentication() -> None:
    response = client.get(f"/api/runtime/executions/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication_required"


def test_legacy_organization_header_does_not_bypass_runtime_authentication() -> None:
    response = client.get(
        "/api/runtime/executions/not-a-uuid",
        headers={"X-Organization-ID": str(uuid4())},
    )

    assert response.status_code == 401


def test_retry_requires_authentication_before_runtime_admin_context() -> None:
    response = client.post(
        f"/api/runtime/executions/{uuid4()}/retry",
        headers={"X-Organization-ID": str(uuid4())},
        json={},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication_required"


def test_create_request_does_not_trust_tenant_in_body_as_identity() -> None:
    response = client.post(
        "/api/runtime/executions",
        json={
            "organization_id": str(uuid4()),
            "execution_type": "generic.operation",
            "subject_type": "generic.subject",
            "subject_id": str(uuid4()),
            "idempotency_key": "request-001",
        },
    )

    assert response.status_code == 401
