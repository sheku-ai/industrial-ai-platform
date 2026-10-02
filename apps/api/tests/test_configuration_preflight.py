from __future__ import annotations

from app.core.config import Settings
from app.services import configuration_preflight


def _production_settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "production",
        "database_url": "postgresql+psycopg://platform_user:generated-password@db.example.com:5432/platform",
        "identity_database_url": "postgresql+psycopg://identity_user:generated-password@identity-db.example.com:5432/identity",
        "object_storage_provider": "s3",
        "object_storage_endpoint_url": "https://object-storage.example.com",
        "object_storage_access_key": "production-access-identifier",
        "object_storage_secret_key": "generated-object-storage-credential",
        "object_storage_bucket": "industrial-ai-production",
        "object_storage_secure": True,
        "authentication_required": True,
        "auth_cookie_secure": True,
        "cors_allowed_origins": "https://portal.example.com",
        "trusted_hosts": "api.example.com",
        "secret_key": "Generated-Only-For-Controlled-Test-123!",
        "secret_store_provider": "redis",
        "secret_store_redis_url": "rediss://cache.example.com:6379/0",
        "database_revision": "20260715_960",
        "debug": False,
    }
    values.update(overrides)
    return Settings(**values)


def _preflight(monkeypatch, settings: Settings):
    monkeypatch.setattr(configuration_preflight, "get_settings", lambda: settings)
    return configuration_preflight.build_configuration_preflight("production")


def test_local_profile_controls_fail_closed_for_production(monkeypatch) -> None:
    result = _preflight(monkeypatch, Settings())

    assert result.status == "failed"


def test_incomplete_production_example_placeholders_fail(monkeypatch) -> None:
    result = _preflight(
        monkeypatch,
        _production_settings(
            database_url="REQUIRED",
            object_storage_access_key="CHANGE_ME",
            object_storage_secret_key="REQUIRED",
            secret_key="CHANGE_ME",
        ),
    )

    assert result.status == "failed"
    assert {blocker.gate_code for blocker in result.blockers} >= {
        "secret_placeholders_absent",
        "secret_key_strong",
    }


def test_controlled_valid_production_profile_passes(monkeypatch) -> None:
    result = _preflight(monkeypatch, _production_settings())

    assert result.status == "passed"


def test_production_security_controls_are_enforced(monkeypatch) -> None:
    result = _preflight(
        monkeypatch,
        _production_settings(
            authentication_required=False,
            cors_allowed_origins="*",
            trusted_hosts="*",
            object_storage_secure=False,
            object_storage_bucket="",
        ),
    )
    checks = {check.setting_code: check.status for check in result.checks}

    assert checks["authentication_enforced"] == "failed"
    assert checks["identity_database_configuration_present"] == "passed"
    assert checks["authentication_cookie_secure"] == "passed"
    assert checks["cors_restricted"] == "failed"
    assert checks["trusted_hosts_restricted"] == "failed"
    assert checks["object_storage_transport_secure"] == "failed"
    assert checks["object_storage_bucket_present"] == "blocked"


def test_explicit_filesystem_provider_does_not_require_remote_controls(monkeypatch, tmp_path) -> None:
    result = _preflight(
        monkeypatch,
        _production_settings(
            object_storage_provider="filesystem",
            object_storage_endpoint_url="http://127.0.0.1:9000",
            object_storage_access_key="minioadmin",
            object_storage_secret_key="minioadmin",
            object_storage_bucket="",
            object_storage_secure=False,
            filesystem_storage_root=str(tmp_path),
        ),
    )
    checks = {check.setting_code: check for check in result.checks}

    assert result.status == "passed"
    assert checks["object_storage_url_production_safe"].status == "passed"
    assert checks["object_storage_url_production_safe"].reason == "not_required_for_filesystem_provider"
    assert checks["object_storage_transport_secure"].status == "passed"
    assert checks["object_storage_bucket_present"].status == "passed"
    assert checks["development_credentials_absent"].status == "passed"


def test_remote_provider_rejects_loopback_http_and_development_credentials(monkeypatch) -> None:
    result = _preflight(
        monkeypatch,
        _production_settings(
            object_storage_provider="s3",
            object_storage_endpoint_url="http://127.0.0.1:9000",
            object_storage_access_key="minioadmin",
            object_storage_secret_key="minioadmin",
            object_storage_secure=False,
        ),
    )
    checks = {check.setting_code: check for check in result.checks}

    assert result.status == "failed"
    assert checks["object_storage_url_production_safe"].status == "failed"
    assert checks["object_storage_transport_secure"].status == "failed"
    assert checks["development_credentials_absent"].status == "failed"
