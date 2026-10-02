from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"


def compose_text() -> str:
    return COMPOSE_FILE.read_text(encoding="utf-8")


def test_container_database_url_is_isolated_from_host_database_url() -> None:
    text = compose_text()

    assert "DATABASE_URL: ${CONTAINER_DATABASE_URL:-" in text
    assert "@postgres:5432/industrial_ai" in text
    assert "DATABASE_URL: ${DATABASE_URL:-" not in text


def test_container_ollama_url_uses_internal_service_dns() -> None:
    text = compose_text()

    assert "OLLAMA_BASE_URL: ${CONTAINER_OLLAMA_BASE_URL:-http://ollama:11434}" in text
    assert "OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-" not in text


def test_container_object_storage_configuration_is_namespaced() -> None:
    text = compose_text()

    expected_variables = (
        "CONTAINER_OBJECT_STORAGE_PROVIDER",
        "CONTAINER_OBJECT_STORAGE_ENDPOINT_URL",
        "CONTAINER_OBJECT_STORAGE_REGION",
        "CONTAINER_OBJECT_STORAGE_ACCESS_KEY",
        "CONTAINER_OBJECT_STORAGE_SECRET_KEY",
        "CONTAINER_OBJECT_STORAGE_BUCKET",
        "CONTAINER_OBJECT_STORAGE_SECURE",
    )

    for variable in expected_variables:
        assert f"${{{variable}" in text

    assert "OBJECT_STORAGE_ENDPOINT_URL: ${OBJECT_STORAGE_ENDPOINT_URL:-" not in text
    assert "OBJECT_STORAGE_ACCESS_KEY: ${OBJECT_STORAGE_ACCESS_KEY:-" not in text
    assert "OBJECT_STORAGE_SECRET_KEY: ${OBJECT_STORAGE_SECRET_KEY:-" not in text


def test_core_compose_defaults_do_not_enable_optional_dependencies() -> None:
    text = compose_text()

    for setting in (
        "OBJECT_STORAGE_PROVIDER: ${CONTAINER_OBJECT_STORAGE_PROVIDER:-filesystem}",
        "OBJECT_STORAGE_ENDPOINT_URL: ${CONTAINER_OBJECT_STORAGE_ENDPOINT_URL:-}",
        "OBJECT_STORAGE_ACCESS_KEY: ${CONTAINER_OBJECT_STORAGE_ACCESS_KEY:-}",
        "OBJECT_STORAGE_SECRET_KEY: ${CONTAINER_OBJECT_STORAGE_SECRET_KEY:-}",
        "OBJECT_STORAGE_BUCKET: ${CONTAINER_OBJECT_STORAGE_BUCKET:-}",
        "SECRET_STORE_PROVIDER: ${SECRET_STORE_PROVIDER:-memory}",
        "SECRET_STORE_REDIS_URL: ${CONTAINER_SECRET_STORE_REDIS_URL:-}",
    ):
        assert setting in text

    api = text.split("\n  api:\n", 1)[1].split("\n  scheduler:\n", 1)[0]
    assert "*object-storage-environment" in api
    assert "*secret-store-environment" in api
    assert "      OBJECT_STORAGE_" not in api
    assert "      SECRET_STORE_" not in api
    assert "      redis:" not in api
    assert "      minio" not in api


def test_optional_profiles_preserve_services_and_explicit_shared_configuration() -> None:
    text = compose_text()

    redis = text.split("\n  redis:\n", 1)[1].split("\n  migrator:\n", 1)[0]
    minio = text.split("\n  minio:\n", 1)[1].split("\n  minio-init:\n", 1)[0]
    minio_init = text.split("\n  minio-init:\n", 1)[1].split("\n  ollama:\n", 1)[0]
    worker = text.split("\n  ingestion-worker:\n", 1)[1].split("\n  worker-monitor:\n", 1)[0]
    assert 'profiles: ["ingestion"]' in redis
    assert 'profiles: ["object-storage", "ingestion"]' in minio
    assert 'profiles: ["object-storage", "ingestion"]' in minio_init
    assert 'profiles: ["ingestion"]' in worker
    assert "*object-storage-environment" in worker
    assert "*secret-store-environment" in worker
    assert "      OBJECT_STORAGE_" not in worker
    assert "      SECRET_STORE_" not in worker
    assert "      redis:" in worker
    assert "      minio-init:" in worker
    for variable in (
        "CONTAINER_OBJECT_STORAGE_PROVIDER",
        "CONTAINER_OBJECT_STORAGE_ENDPOINT_URL",
        "CONTAINER_OBJECT_STORAGE_BUCKET",
        "CONTAINER_OBJECT_STORAGE_ACCESS_KEY",
        "CONTAINER_OBJECT_STORAGE_SECRET_KEY",
        "SECRET_STORE_PROVIDER",
        "CONTAINER_SECRET_STORE_REDIS_URL",
    ):
        assert f"${{{variable}:-" in text
