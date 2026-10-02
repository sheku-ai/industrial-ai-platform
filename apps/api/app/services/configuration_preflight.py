from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.schemas.production_acceptance import (
    ConfigurationPreflightCheck,
    ConfigurationPreflightResult,
    ProductionBlocker,
    ProductionWarning,
)
from app.services.database_revision import resolve_database_revision

PREFLIGHT_PROFILES = ("development", "test", "acceptance", "production")
UNSAFE_PLACEHOLDERS = {
    "change_me",
    "changeme",
    "default",
    "password",
    "secret",
    "admin",
    "dummy",
    "empty",
    "example",
    "null",
    "none",
    "undefined",
    "test",
}
SENSITIVE_TOKENS = ("password", "token", "secret", "access_key", "private", "jwt", "encryption", "database_url")
CONFIGURATION_EVIDENCE_ORIGIN = "configuration_preflight.get_settings"
DEVELOPMENT_CREDENTIAL_MARKERS = (
    "minioadmin",
    "industrial_ai:industrial_ai",
    "postgres:postgres",
    "redis://localhost",
)
SUPPORTED_OBJECT_STORAGE_PROVIDERS = {"filesystem", "s3", "minio", "object_storage"}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _is_missing(value: Any) -> bool:
    return _normalize(value).lower() in {"", "null", "none", "undefined", "unknown"}


def _contains_credential_url(value: str) -> bool:
    return bool(re.search(r"://[^/\s:]+:[^@\s]+@", value))


def is_placeholder_value(value: Any) -> bool:
    normalized = _normalize(value).lower()
    if not normalized:
        return True
    compact = re.sub(r"[\s\-]+", "_", normalized)
    return compact in UNSAFE_PLACEHOLDERS


def mask_setting_value(code: str, value: Any, *, sensitive: bool = False) -> str:
    normalized = _normalize(value)
    if _is_missing(normalized):
        return "missing"
    if is_placeholder_value(normalized):
        return "placeholder_detected"
    lowered_code = code.lower()
    if sensitive or any(token in lowered_code for token in SENSITIVE_TOKENS) or _contains_credential_url(normalized):
        return "configured"
    if len(normalized) <= 4:
        return "configured"
    return f"{normalized[:4]}********"


def _status_for_value(
    *,
    value: Any,
    mandatory: bool,
    production_profile: bool,
    sensitive: bool = False,
) -> tuple[str, str]:
    if _is_missing(value):
        return ("blocked" if mandatory else "not_evaluated", "missing")
    if is_placeholder_value(value):
        return ("failed" if production_profile and mandatory else "blocked", "placeholder_detected")
    return "passed", "configured"


def _check(
    code: str,
    source: str,
    value: Any,
    *,
    mandatory: bool = True,
    production_profile: bool,
    sensitive: bool = False,
    evaluated_at: datetime | None = None,
) -> ConfigurationPreflightCheck:
    status, reason = _status_for_value(
        value=value,
        mandatory=mandatory,
        production_profile=production_profile,
        sensitive=sensitive,
    )
    return ConfigurationPreflightCheck(
        setting_code=code,
        status=status,
        source=source,
        masked_value=mask_setting_value(code, value, sensitive=sensitive),
        reason=reason,
        mandatory=mandatory,
        configured=not _is_missing(value),
        placeholder=is_placeholder_value(value) if not _is_missing(value) else False,
        evidence_origin=CONFIGURATION_EVIDENCE_ORIGIN,
        evaluated_at=evaluated_at or datetime.now(UTC),
    )


def _boolean_check(
    code: str,
    source: str,
    passed: bool,
    *,
    mandatory: bool = True,
    failed_reason: str,
    configured: bool = True,
    evaluated_at: datetime | None = None,
) -> ConfigurationPreflightCheck:
    return ConfigurationPreflightCheck(
        setting_code=code,
        status="passed" if passed else "failed",
        source=source,
        masked_value="configured" if passed else "missing",
        reason="configured" if passed else failed_reason,
        mandatory=mandatory,
        configured=configured,
        placeholder=False,
        evidence_origin=CONFIGURATION_EVIDENCE_ORIGIN,
        evaluated_at=evaluated_at or datetime.now(UTC),
    )


def _profile_from_environment() -> str:
    return get_settings().environment_profile.strip()


def production_preflight_required() -> bool:
    return _profile_from_environment().lower() == "production"


def _development_credential_absent(settings: Settings) -> bool:
    provider, _ = _effective_object_storage_provider(settings)
    values = [settings.secret_store_redis_url, settings.database_url]
    if provider != "filesystem":
        values.extend(
            [
                settings.object_storage_access_key,
                settings.object_storage_secret_key,
            ]
        )
    return not any(
        marker in _normalize(value).lower()
        for value in values
        for marker in DEVELOPMENT_CREDENTIAL_MARKERS
    )


def _production_url_safe(value: str) -> bool:
    parsed = urlparse(_normalize(value))
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return False
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        return True


def _production_object_storage_url_safe(value: str) -> bool:
    parsed = urlparse(_normalize(value))
    return parsed.scheme.lower() == "https" and _production_url_safe(value)


def _effective_object_storage_provider(settings: Settings) -> tuple[str | None, str]:
    provider = settings.object_storage_provider.strip().lower()
    if "object_storage_provider" not in settings.model_fields_set:
        return None, "object_storage_provider_not_explicit"
    if not provider:
        return None, "object_storage_provider_missing"
    if provider not in SUPPORTED_OBJECT_STORAGE_PROVIDERS:
        return None, "unsupported_object_storage_provider"
    return provider, "configured"


def _database_schemas_present(db: Session | None) -> bool:
    if db is None:
        return False
    required = {"core", "documents", "ai", "runtime", "audit", "security"}
    try:
        present = set(
            db.scalars(
                text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:schemas)"),
                {"schemas": list(required)},
            )
        )
    except Exception:
        db.rollback()
        return False
    return required.issubset(present)


def _object_storage_bucket_available(settings: Settings) -> bool:
    provider, _ = _effective_object_storage_provider(settings)
    if provider == "filesystem":
        return Path(settings.filesystem_storage_root).is_dir()
    if not settings.object_storage_endpoint_url or not settings.object_storage_bucket:
        return False
    try:
        from app.services.dependency_health import _probe_object_storage

        return _probe_object_storage(settings, timeout_seconds=settings.dependency_probe_timeout_seconds)
    except Exception:
        return False


def _secret_placeholder_absent(settings: Settings) -> bool:
    provider, _ = _effective_object_storage_provider(settings)
    secret_values = [settings.secret_store_redis_url, settings.database_url]
    if provider != "filesystem":
        secret_values.extend(
            [
                settings.object_storage_access_key,
                settings.object_storage_secret_key,
            ]
        )
    return all(not is_placeholder_value(value) for value in secret_values if _normalize(value))


def _cors_restricted(settings: Settings) -> bool:
    origins = settings.cors_origins
    if not origins:
        return False
    for origin in origins:
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        if "*" in origin or host in {"localhost", "127.0.0.1", "host.docker.internal"}:
            return False
    return True


def _trusted_hosts_restricted(settings: Settings) -> bool:
    hosts = settings.trusted_host_list
    return bool(hosts) and all(
        "*" not in host
        and host.lower() not in {"localhost", "127.0.0.1", "host.docker.internal"}
        and not host.lower().endswith(".local")
        for host in hosts
    )


def _secret_key_strong(settings: Settings) -> bool:
    value = settings.secret_key.strip()
    if len(value) < 32 or is_placeholder_value(value):
        return False
    categories = (
        any(character.islower() for character in value),
        any(character.isupper() for character in value),
        any(character.isdigit() for character in value),
        any(not character.isalnum() for character in value),
    )
    return sum(categories) >= 3


def _redis_configuration_safe(settings: Settings) -> bool:
    if settings.secret_store_provider.strip().lower() != "redis":
        return False
    value = settings.secret_store_redis_url.strip()
    return bool(value) and not is_placeholder_value(value) and _production_url_safe(value)


def _provider_execution_explicit(settings: Settings) -> bool:
    if not settings.feature_embeddings_enabled and not settings.feature_vector_retrieval_enabled:
        return True
    return bool(settings.object_storage_bucket or settings.object_storage_endpoint_url)


def _setting_contract_check(
    setting_code: str,
    value: Any,
    *,
    evaluated_at: datetime,
    sensitive: bool = False,
    unsafe_reason: str | None = None,
    mandatory: bool = True,
) -> ConfigurationPreflightCheck:
    check = _check(
        setting_code,
        f"settings.{setting_code}",
        value,
        production_profile=True,
        sensitive=sensitive,
        evaluated_at=evaluated_at,
        mandatory=mandatory,
    )
    if check.status == "passed" and unsafe_reason is not None:
        return check.model_copy(update={"status": "failed", "reason": unsafe_reason})
    return check


def build_configuration_evidence_contract() -> list[ConfigurationPreflightCheck]:
    """Return the sanitized, authoritative configuration evidence consumed by runtimes."""
    settings = get_settings()
    evaluated_at = datetime.now(UTC)
    effective_provider, _ = _effective_object_storage_provider(settings)
    filesystem_provider = effective_provider == "filesystem"
    endpoint = settings.object_storage_endpoint_url
    endpoint_unsafe = bool(endpoint) and not _production_object_storage_url_safe(endpoint)
    access_key_unsafe = any(
        marker in _normalize(settings.object_storage_access_key).lower()
        for marker in DEVELOPMENT_CREDENTIAL_MARKERS
    )
    secret_key_unsafe = any(
        marker in _normalize(settings.object_storage_secret_key).lower()
        for marker in DEVELOPMENT_CREDENTIAL_MARKERS
    )
    authentication_configured = settings.authentication_required is not None
    checks = [
        _setting_contract_check(
            "object_storage_endpoint_url",
            endpoint,
            evaluated_at=evaluated_at,
            unsafe_reason="localhost_or_private_object_storage_url_detected" if endpoint_unsafe else None,
            mandatory=not filesystem_provider,
        ),
        _setting_contract_check(
            "object_storage_bucket",
            settings.object_storage_bucket,
            evaluated_at=evaluated_at,
            mandatory=not filesystem_provider,
        ),
        _setting_contract_check(
            "object_storage_access_key",
            settings.object_storage_access_key,
            evaluated_at=evaluated_at,
            sensitive=True,
            unsafe_reason="development_credentials_detected" if access_key_unsafe else None,
            mandatory=not filesystem_provider,
        ),
        _setting_contract_check(
            "object_storage_secret_key",
            settings.object_storage_secret_key,
            evaluated_at=evaluated_at,
            sensitive=True,
            unsafe_reason="development_credentials_detected" if secret_key_unsafe else None,
            mandatory=not filesystem_provider,
        ),
        _boolean_check(
            "object_storage_tls",
            "settings.object_storage_secure",
            filesystem_provider or bool(settings.object_storage_secure),
            failed_reason="object_storage_tls_disabled",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "authentication",
            "settings.authentication_required",
            settings.authentication_required is True,
            failed_reason=(
                "authentication_not_enforced"
                if authentication_configured
                else "authentication_requirement_not_configured"
            ),
            configured=authentication_configured,
            evaluated_at=evaluated_at,
        ),
        _setting_contract_check(
            "identity_database_url",
            settings.identity_database_url,
            evaluated_at=evaluated_at,
            sensitive=True,
        ),
        _boolean_check(
            "authentication_cookie_secure",
            "settings.auth_cookie_secure",
            bool(settings.auth_cookie_secure),
            failed_reason="authentication_cookie_not_secure",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "cors",
            "settings.cors_allowed_origins",
            _cors_restricted(settings),
            failed_reason="cors_allows_development_or_wildcard_origins",
            configured=bool(settings.cors_allowed_origins.strip()),
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "debug",
            "settings.debug",
            not settings.debug,
            failed_reason="debug_enabled",
            evaluated_at=evaluated_at,
        ),
        _setting_contract_check(
            "database_url",
            settings.database_url,
            evaluated_at=evaluated_at,
            sensitive=True,
        ),
        _setting_contract_check(
            "secret_store_provider",
            settings.secret_store_provider,
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "feature_embeddings_enabled",
            "settings.feature_embeddings_enabled",
            True,
            mandatory=False,
            failed_reason="feature_flag_invalid",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "feature_vector_retrieval_enabled",
            "settings.feature_vector_retrieval_enabled",
            True,
            mandatory=False,
            failed_reason="feature_flag_invalid",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "provider_execution_explicit",
            "settings.feature_flags",
            _provider_execution_explicit(settings),
            failed_reason="provider_execution_not_explicit",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "ai_optional",
            "settings.feature_flags",
            True,
            mandatory=False,
            failed_reason="ai_feature_required",
            evaluated_at=evaluated_at,
        ),
    ]
    if filesystem_provider:
        return [
            check.model_copy(
                update={
                    "status": "passed",
                    "reason": "not_required_for_filesystem_provider",
                    "masked_value": "not_required",
                    "configured": False,
                    "placeholder": False,
                }
            )
            if check.setting_code
            in {
                "object_storage_endpoint_url",
                "object_storage_access_key",
                "object_storage_secret_key",
                "object_storage_bucket",
            }
            else check
            for check in checks
        ]
    return checks


def build_configuration_preflight(
    profile: str = "production",
    *,
    db: Session | None = None,
    probe_dependencies: bool = False,
) -> ConfigurationPreflightResult:
    started = perf_counter()
    evaluated_at = datetime.now(UTC)
    normalized_profile = (profile or "production").strip().lower()
    if normalized_profile not in PREFLIGHT_PROFILES:
        normalized_profile = "production"
    production_profile = normalized_profile == "production"
    settings = get_settings()
    effective_provider, provider_reason = _effective_object_storage_provider(settings)
    filesystem_provider = effective_provider == "filesystem"
    environment_profile = settings.environment_profile.strip()
    configuration_contract = {
        check.setting_code: check for check in build_configuration_evidence_contract()
    }
    endpoint_contract = configuration_contract["object_storage_endpoint_url"]
    bucket_contract = configuration_contract["object_storage_bucket"]
    checks = [
        _check(
            "environment_profile_explicit",
            "environment",
            environment_profile,
            production_profile=production_profile,
            evaluated_at=evaluated_at,
        ),
        _check(
            "database_configuration_present",
            "settings.database_url",
            settings.database_url,
            production_profile=production_profile,
            sensitive=True,
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "object_storage_configuration_present",
            CONFIGURATION_EVIDENCE_ORIGIN,
            (
                bool(settings.filesystem_storage_root)
                if filesystem_provider
                else endpoint_contract.configured
            )
            and (True if filesystem_provider else bucket_contract.configured),
            failed_reason="missing",
            configured=(
                bool(settings.filesystem_storage_root)
                if filesystem_provider
                else endpoint_contract.configured
            )
            and (True if filesystem_provider else bucket_contract.configured),
            evaluated_at=evaluated_at,
        ),
        bucket_contract.model_copy(update={"setting_code": "object_storage_bucket_present"}),
        _boolean_check(
            "object_storage_provider_supported",
            "settings.object_storage_provider",
            effective_provider is not None,
            failed_reason=provider_reason,
            configured=effective_provider is not None,
            evaluated_at=evaluated_at,
        ),
        configuration_contract["authentication"].model_copy(
            update={"setting_code": "authentication_enforced"}
        ),
        configuration_contract["identity_database_url"].model_copy(
            update={"setting_code": "identity_database_configuration_present"}
        ),
        configuration_contract["authentication_cookie_secure"].model_copy(
            update={"setting_code": "authentication_cookie_secure"}
        ),
        configuration_contract["cors"].model_copy(
            update={"setting_code": "cors_restricted"}
        ),
        _boolean_check(
            "trusted_hosts_restricted",
            "settings.trusted_hosts",
            not production_profile or _trusted_hosts_restricted(settings),
            failed_reason="trusted_hosts_missing_or_unsafe",
            configured=bool(settings.trusted_hosts.strip()),
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "secret_key_strong",
            "settings.secret_key",
            not production_profile or _secret_key_strong(settings),
            failed_reason="secret_key_missing_placeholder_or_weak",
            configured=bool(settings.secret_key.strip()),
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "redis_configuration_safe",
            "settings.secret_store_redis_url",
            not production_profile or _redis_configuration_safe(settings),
            failed_reason="redis_configuration_missing_or_unsafe",
            configured=bool(settings.secret_store_redis_url.strip()),
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "secret_placeholders_absent",
            "settings",
            _secret_placeholder_absent(settings),
            failed_reason="unsafe_secret_placeholder_detected",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "development_credentials_absent",
            "settings",
            not production_profile or _development_credential_absent(settings),
            failed_reason="development_credentials_detected",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "database_url_production_safe",
            "settings.database_url",
            not production_profile or _production_url_safe(settings.database_url),
            failed_reason="localhost_or_private_database_url_detected",
            evaluated_at=evaluated_at,
        ),
        endpoint_contract.model_copy(
            update={
                "setting_code": "object_storage_url_production_safe",
                "status": "passed"
                if not production_profile or filesystem_provider
                else endpoint_contract.status,
                "reason": "not_required_for_filesystem_provider"
                if filesystem_provider
                else "configured"
                if not production_profile
                else endpoint_contract.reason,
            }
        ),
        configuration_contract["object_storage_tls"].model_copy(
            update={
                "setting_code": "object_storage_transport_secure",
                "status": "passed"
                if not production_profile
                else configuration_contract["object_storage_tls"].status,
                "reason": "configured"
                if not production_profile
                else configuration_contract["object_storage_tls"].reason,
            }
        ),
        _boolean_check(
            "database_schemas_present",
            "postgresql.pg_namespace",
            (not probe_dependencies) or _database_schemas_present(db),
            failed_reason="required_database_schema_missing",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "object_storage_bucket_available",
            "object_storage.head_bucket",
            (not probe_dependencies) or _object_storage_bucket_available(settings),
            failed_reason="object_storage_bucket_unavailable",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "feature_flags_compatible",
            "settings.feature_flags",
            not settings.feature_vector_retrieval_enabled or settings.feature_embeddings_enabled,
            failed_reason="vector_retrieval_requires_embeddings",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "provider_execution_explicit",
            "settings.feature_flags",
            _provider_execution_explicit(settings),
            failed_reason="provider_execution_not_explicit",
            evaluated_at=evaluated_at,
        ),
        _boolean_check(
            "ai_optional",
            "settings.feature_flags",
            True,
            mandatory=False,
            failed_reason="ai_feature_required",
            evaluated_at=evaluated_at,
        ),
        configuration_contract["debug"].model_copy(
            update={"setting_code": "debug_disabled"}
        ),
        _check(
            "application_version_present",
            "settings.app_version",
            settings.app_version,
            production_profile=production_profile,
            evaluated_at=evaluated_at,
        ),
        _check(
            "database_schema_version_present",
            "postgresql.alembic_version" if db is not None else "settings.database_revision",
            resolve_database_revision(db) if db is not None else settings.database_revision,
            production_profile=production_profile,
            evaluated_at=evaluated_at,
        ),
    ]
    blockers = [
        ProductionBlocker(
            code=f"{check.setting_code}_not_ready",
            gate_code=check.setting_code,
            domain="configuration",
            message=check.reason,
        )
        for check in checks
        if check.mandatory and check.status in {"failed", "blocked"}
    ]
    warnings: list[ProductionWarning] = []
    status = "passed"
    if any(check.status == "failed" for check in checks if check.mandatory):
        status = "failed"
    elif any(check.status == "blocked" for check in checks if check.mandatory):
        status = "blocked"
    elif all(check.status == "not_evaluated" for check in checks):
        status = "not_evaluated"
    return ConfigurationPreflightResult(
        profile=normalized_profile,
        status=status,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        postgresql_source_of_truth=True,
        secrets_exposed=False,
        evaluated_at=evaluated_at,
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
    )
