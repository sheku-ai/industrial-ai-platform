from __future__ import annotations

from fastapi.testclient import TestClient

import main
from app.api.dependencies.authentication import get_authenticated_principal
from app.core.config import Settings
from app.services.effective_configuration import resolve_effective_configuration


def test_effective_configuration_exposes_runtime_values_without_secrets() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://platform_user:database-secret@postgres:5432/platform_db",
        portal_port=3100,
        cors_allowed_origins="http://localhost:3100,http://127.0.0.1:3100",
        object_storage_endpoint_url="http://minio:9000",
        object_storage_access_key="storage-user",
        object_storage_secret_key="storage-secret",
        object_storage_bucket="platform-artifacts",
        feature_worker_enabled=True,
        feature_embeddings_enabled=True,
        build_commit="abc123",
    )

    result = resolve_effective_configuration(
        settings,
        database_revision="20260620_2350",
        configuration_revision="config-123",
    )
    payload = result.model_dump(mode="json")
    serialized = result.model_dump_json()

    assert payload["portal_port"] == 3100
    assert payload["cors_origins"] == [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
    assert payload["database"] == {
        "configured": True,
        "driver": "postgresql+psycopg",
        "host": "postgres",
        "port": 5432,
        "database": "platform_db",
    }
    assert payload["object_storage"]["enabled"] is True
    assert payload["object_storage"]["endpoint_host"] == "minio"
    assert payload["object_storage"]["endpoint_port"] == 9000
    assert payload["object_storage"]["credentials_configured"] is True
    assert payload["feature_flags"]["worker"] is True
    assert payload["feature_flags"]["embeddings"] is True
    assert payload["provider_execution_enabled"] is False

    assert "database-secret" not in serialized
    assert "storage-secret" not in serialized
    assert "storage-user" not in serialized
    assert "platform_user" not in serialized


def test_effective_configuration_reports_disabled_optional_services() -> None:
    result = resolve_effective_configuration(
        Settings(database_url=""),
        database_revision="unknown",
        configuration_revision="unknown",
    )

    assert result.database.configured is False
    assert result.object_storage.enabled is False
    assert result.object_storage.credentials_configured is False
    assert result.provider_execution_enabled is False


def test_effective_configuration_route_returns_redacted_contract(monkeypatch) -> None:
    expected = resolve_effective_configuration(
        Settings(
            database_url="postgresql+psycopg://user:secret@postgres:5432/platform",
            portal_port=3100,
        ),
        database_revision="db-revision",
        configuration_revision="configuration-revision",
    )
    monkeypatch.setattr(main, "_effective_configuration", lambda: expected)
    main.app.dependency_overrides[get_authenticated_principal] = lambda: object()

    try:
        response = TestClient(main.app).get("/platform/configuration")
    finally:
        main.app.dependency_overrides.pop(get_authenticated_principal, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["portal_port"] == 3100
    assert payload["database"]["host"] == "postgres"
    assert payload["database_revision"] == "db-revision"
    assert "secret" not in response.text
    assert "user" not in payload["database"]
