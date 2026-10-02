import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.schemas.recovery import RestoreVerificationCompleteRequest
from app.services import configuration_preflight
from app.services.correlation_context import CorrelationIdMiddleware
from app.services.production_acceptance_runtime import _mandatory_acceptance_gates_passed
from app.services.recovery_runtime import _verification_passed


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_correlation_middleware_generates_and_propagates_identifier() -> None:
    response = _client().get("/probe")

    assert response.status_code == 200
    assert uuid.UUID(response.headers["X-Correlation-ID"])


def test_correlation_middleware_preserves_valid_identifier_and_rejects_invalid() -> None:
    client = _client()

    response = client.get("/probe", headers={"X-Correlation-ID": "production/readiness-42"})
    invalid = client.get("/probe", headers={"X-Correlation-ID": "unsafe correlation value"})

    assert response.headers["X-Correlation-ID"] == "production/readiness-42"
    assert invalid.status_code == 400


def test_production_preflight_fails_closed_without_production_controls(monkeypatch) -> None:
    monkeypatch.delenv("AUTHENTICATION_REQUIRED", raising=False)
    monkeypatch.delenv("IDENTITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    for variable in (
        "ENVIRONMENT_PROFILE",
        "APP_ENV",
        "ENVIRONMENT",
        "DEPLOYMENT_ENVIRONMENT",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://industrial_ai:industrial_ai@localhost:5432/industrial_ai",
        authentication_required=None,
        identity_database_url="",
        auth_cookie_secure=False,
        object_storage_provider="s3",
        object_storage_endpoint_url="http://127.0.0.1:9000",
        object_storage_access_key="minioadmin",
        object_storage_secret_key="minioadmin",
        object_storage_bucket="industrial-ai",
        object_storage_secure=False,
        cors_allowed_origins="*",
    )
    monkeypatch.setattr(configuration_preflight, "get_settings", lambda: settings)

    result = configuration_preflight.build_configuration_preflight("production")
    checks = {item.setting_code: item for item in result.checks}

    assert result.status == "failed"
    assert result.secrets_exposed is False
    assert checks["development_credentials_absent"].status == "failed"
    assert checks["database_url_production_safe"].status == "failed"
    assert checks["object_storage_url_production_safe"].status == "failed"
    assert checks["object_storage_provider_supported"].status == "passed"
    assert checks["object_storage_provider_supported"].reason == "configured"
    assert checks["authentication_enforced"].status == "failed"
    assert checks["identity_database_configuration_present"].status == "blocked"
    assert checks["authentication_cookie_secure"].status == "failed"
    assert checks["cors_restricted"].status == "failed"


def test_restore_verification_requires_complete_product_runtime_evidence() -> None:
    incomplete = RestoreVerificationCompleteRequest(
        database_connectivity_verified=True,
        schema_version_verified=True,
        record_counts_verified=True,
        object_storage_access_verified=True,
        artifact_checksums_verified=True,
        organization_isolation_verified=True,
        knowledge_lineage_verified=True,
        enterprise_search_verified=True,
        conversation_persistence_verified=True,
        document_registration_verified=True,
        assistant_runtime_verified=True,
        audit_runtime_verified=False,
    )

    assert _verification_passed(incomplete) is False
    assert _verification_passed(incomplete.model_copy(update={"audit_runtime_verified": True})) is True


def test_zero_configured_acceptance_gates_do_not_create_a_false_blocker() -> None:
    evidence = {
        "release_candidate_eligible": True,
        "mandatory_gates_passed": 0,
        "mandatory_gates_total": 0,
    }

    assert _mandatory_acceptance_gates_passed(evidence) is True
    assert _mandatory_acceptance_gates_passed({**evidence, "release_candidate_eligible": False}) is False
