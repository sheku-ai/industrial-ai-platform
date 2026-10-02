from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import main
from app.api.dependencies.authentication import get_authenticated_principal
from app.core.config import Settings
from app.schemas.dependency_health import DependencyHealthItem, DependencyHealthResponse
from app.services.dependency_health import build_readiness, evaluate_dependency_health


class HealthySession:
    def execute(self, _statement):
        return object()

    def rollback(self) -> None:
        raise AssertionError("rollback should not be called")

    def scalar(self, _statement, _parameters=None):
        return True


class BrokenSession:
    def execute(self, _statement):
        raise RuntimeError("database unavailable")

    def rollback(self) -> None:
        return None

    def scalar(self, _statement, _parameters=None):
        raise RuntimeError("database unavailable")


def test_disabled_optional_dependencies_do_not_degrade_readiness() -> None:
    snapshot = evaluate_dependency_health(
        HealthySession(),
        Settings(
            database_url="postgresql+psycopg://user:secret@postgres:5432/platform",
            feature_embeddings_enabled=False,
            feature_vector_retrieval_enabled=False,
            object_storage_endpoint_url="",
            object_storage_bucket="",
        ),
        identity_session=HealthySession(),
    )

    assert snapshot.status == "healthy"
    by_name = {item.name: item for item in snapshot.dependencies}
    assert by_name["postgresql"].status == "healthy"
    assert by_name["postgresql"].lifecycle_state == "ready"
    assert by_name["object_storage"].status == "disabled"
    assert by_name["embeddings"].status == "disabled"
    assert by_name["vector_retrieval"].status == "disabled"
    assert by_name["ai_provider_execution"].status == "disabled"
    assert by_name["ai_provider_execution"].lifecycle_state == "alive"
    assert build_readiness(snapshot).status == "ready"


def test_unavailable_required_database_fails_readiness() -> None:
    snapshot = evaluate_dependency_health(
        BrokenSession(),
        Settings(),
        identity_session=HealthySession(),
    )
    readiness = build_readiness(snapshot)

    assert snapshot.status == "critical"
    assert readiness.status == "not_ready"
    assert readiness.required_dependencies[0].name == "postgresql"
    assert readiness.required_dependencies[0].status == "unavailable"
    assert readiness.lifecycle_state == "unavailable"


def test_enabled_but_incomplete_optional_dependency_is_reported_without_blocking_readiness() -> None:
    snapshot = evaluate_dependency_health(
        HealthySession(),
        Settings(object_storage_endpoint_url="http://minio:9000", object_storage_bucket=""),
        identity_session=HealthySession(),
    )
    by_name = {item.name: item for item in snapshot.dependencies}

    assert by_name["object_storage"].enabled is True
    assert by_name["object_storage"].status == "not_configured"
    assert by_name["object_storage"].lifecycle_state == "degraded"
    assert build_readiness(snapshot).status == "ready"


def test_optional_dependency_outage_degrades_inventory_without_blocking_core() -> None:
    snapshot = evaluate_dependency_health(
        HealthySession(),
        Settings(
            object_storage_endpoint_url="http://minio:9000",
            object_storage_bucket="platform",
            secret_store_provider="redis",
            secret_store_redis_url="redis://redis:6379/0",
        ),
        identity_session=HealthySession(),
        object_storage_probe=lambda: False,
        redis_probe=lambda: True,
    )
    by_name = {item.name: item for item in snapshot.dependencies}

    assert snapshot.status == "degraded"
    assert by_name["object_storage"].status == "unavailable"
    assert by_name["object_storage"].lifecycle_state == "degraded"
    assert by_name["redis_secret_store"].lifecycle_state == "ready"
    assert build_readiness(snapshot).status == "ready"


def test_health_routes_keep_contracts_separate(monkeypatch) -> None:
    dependency_snapshot = DependencyHealthResponse(
        status="healthy",
        checked_at=datetime.now(UTC),
        dependencies=[
            DependencyHealthItem(
                name="postgresql",
                required=True,
                enabled=True,
                status="healthy",
                lifecycle_state="ready",
            ),
            DependencyHealthItem(
                name="object_storage",
                required=False,
                enabled=False,
                status="disabled",
                lifecycle_state="alive",
            ),
        ],
    )
    monkeypatch.setattr(main, "_dependency_health", lambda: dependency_snapshot)
    main.app.dependency_overrides[get_authenticated_principal] = lambda: object()

    try:
        client = TestClient(main.app)
        readiness = client.get("/health/ready")
        dependencies = client.get("/health/dependencies")
    finally:
        main.app.dependency_overrides.pop(get_authenticated_principal, None)

    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ready"
    assert readiness.json()["required_dependencies"][0]["name"] == "postgresql"
    assert dependencies.status_code == 200
    assert len(dependencies.json()["dependencies"]) == 2


def test_dependency_route_returns_503_when_required_dependency_is_unavailable(monkeypatch) -> None:
    snapshot = DependencyHealthResponse(
        status="critical",
        checked_at=datetime.now(UTC),
        dependencies=[
            DependencyHealthItem(
                name="postgresql",
                required=True,
                enabled=True,
                status="unavailable",
                lifecycle_state="unavailable",
            )
        ],
    )
    monkeypatch.setattr(main, "_dependency_health", lambda: snapshot)
    main.app.dependency_overrides[get_authenticated_principal] = lambda: object()

    try:
        client = TestClient(main.app)

        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/dependencies").status_code == 503
    finally:
        main.app.dependency_overrides.pop(get_authenticated_principal, None)


def test_identity_database_is_a_required_readiness_dependency() -> None:
    snapshot = evaluate_dependency_health(
        HealthySession(),
        Settings(),
        identity_session=BrokenSession(),
    )
    readiness = build_readiness(snapshot)
    by_name = {item.name: item for item in snapshot.dependencies}

    assert by_name["identity_postgresql"].required is True
    assert by_name["identity_postgresql"].status == "unavailable"
    assert readiness.status == "not_ready"
