from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
API_DOCKERFILE = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
PORTAL_DOCKERFILE = (ROOT / "apps" / "admin-portal" / "Dockerfile").read_text(encoding="utf-8")
PORTAL_PROXY_ROUTE = (
    ROOT / "apps" / "admin-portal" / "app" / "api" / "[...path]" / "route.ts"
).read_text(
    encoding="utf-8"
)
PORTAL_PROXY_HELPER = (ROOT / "apps" / "admin-portal" / "lib" / "server" / "api-proxy.ts").read_text(
    encoding="utf-8"
)


def test_required_container_services_are_declared() -> None:
    for service in ("postgres", "migrator", "api", "scheduler", "portal"):
        assert f"  {service}:" in COMPOSE


def test_optional_capabilities_use_profiles() -> None:
    assert 'profiles: ["object-storage", "ingestion"]' in COMPOSE
    assert 'profiles: ["ai"]' in COMPOSE
    assert 'profiles: ["ingestion"]' in COMPOSE


def test_api_and_scheduler_wait_for_migrations() -> None:
    assert COMPOSE.count("condition: service_completed_successfully") >= 3
    assert 'command: ["python", "migration_guard.py", "apply"]' in COMPOSE
    assert 'command: ["alembic", "-c", "identity_alembic.ini", "upgrade", "head"]' in COMPOSE


def test_runtime_health_contract_is_declared() -> None:
    assert "/health/ready" in COMPOSE
    assert "/operations" in COMPOSE
    assert "service_healthy" in COMPOSE


def test_ai_and_vector_capabilities_default_to_disabled() -> None:
    assert "FEATURE_EMBEDDINGS_ENABLED: ${FEATURE_EMBEDDINGS_ENABLED:-false}" in COMPOSE
    assert "FEATURE_VECTOR_RETRIEVAL_ENABLED: ${FEATURE_VECTOR_RETRIEVAL_ENABLED:-false}" in COMPOSE


def test_api_image_runs_as_non_root_user() -> None:
    assert "USER platform" in API_DOCKERFILE
    assert "python:3.12-slim" in API_DOCKERFILE


def test_portal_api_origin_is_deployment_configured() -> None:
    assert "ARG NEXT_PUBLIC_API_BASE_URL" in PORTAL_DOCKERFILE
    assert "http://localhost:8000" not in PORTAL_DOCKERFILE
    assert "API_INTERNAL_BASE_URL:" in COMPOSE
    assert "PORTAL_API_INTERNAL_BASE_URL" in COMPOSE
    assert "createApiProxy" in PORTAL_PROXY_ROUTE
    assert "createApiProxy('api')" in PORTAL_PROXY_ROUTE
    assert "API_INTERNAL_BASE_URL" not in PORTAL_PROXY_ROUTE
    assert "import 'server-only'" in PORTAL_PROXY_HELPER
    assert "process.env.API_INTERNAL_BASE_URL" in PORTAL_PROXY_HELPER
    assert "NEXT_PUBLIC_API_BASE_URL" not in PORTAL_PROXY_HELPER
    assert "if (!apiBaseUrl)" in PORTAL_PROXY_HELPER
    assert "{ status: 502" in PORTAL_PROXY_HELPER
    assert "request.nextUrl.origin" not in PORTAL_PROXY_HELPER
    assert "request.headers.get('API_INTERNAL_BASE_URL')" not in PORTAL_PROXY_HELPER
    assert "http://localhost:8000" not in PORTAL_PROXY_HELPER
    assert "host.docker.internal" not in PORTAL_PROXY_HELPER
    assert "npm run build:portal" in PORTAL_DOCKERFILE
