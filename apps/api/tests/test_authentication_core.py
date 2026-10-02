from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from argon2 import PasswordHasher, Type
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.api.dependencies.authentication import get_authenticated_principal, require_full_access_principal
from app.api.dependencies.runtime_context import get_runtime_context
from app.cli.__main__ import _password_from_environment, build_parser
from app.core.config import Settings
from app.db.session import get_db
from app.identity.contracts import AuthenticatedPrincipal
from app.identity.db import get_identity_db
from app.identity.models import AuthSession, IdentityUser, OrganizationMembership
from app.identity.passwords import PasswordContext, PasswordManager, PasswordPolicyError
from app.identity.service import hash_secret, normalize_email, normalize_username
from app.security.api_policy import required_permissions
from app.security.client_ip import resolve_client_ip
from main import app


def _settings(**updates) -> Settings:
    values = {
        "auth_argon2_time_cost": 2,
        "auth_argon2_memory_cost_kib": 8_192,
        "auth_argon2_parallelism": 1,
        "auth_session_absolute_seconds": 3_600,
        "auth_session_inactivity_seconds": 1_800,
        "auth_session_touch_interval_seconds": 60,
    }
    values.update(updates)
    return Settings(**values)


def _principal(organization_id: uuid.UUID) -> AuthenticatedPrincipal:
    now = datetime.now(UTC)
    user = IdentityUser(
        username="administrator",
        id=uuid.uuid4(),
        email_normalized="operator@example.test",
        email_display="Operator@Example.test",
        status="active",
        must_change_password=False,
    )
    auth_session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_secret("opaque-token"),
        created_at=now,
        last_activity_at=now,
        idle_expires_at=now + timedelta(minutes=30),
        absolute_expires_at=now + timedelta(hours=1),
        idle_timeout_seconds=1_800,
        policy_version=1,
        remember_me=False,
        updated_at=now,
        metadata_json={},
    )
    membership = OrganizationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=organization_id,
        role_id=uuid.uuid4(),
        status="active",
    )
    return AuthenticatedPrincipal(user=user, session=auth_session, memberships=(membership,))


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/runtime/executions",
            "headers": headers or [],
            "client": ("127.0.0.1", 1234),
        }
    )


def _client_request(peer: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": headers or [],
            "client": (peer, 443),
        }
    )


def test_client_ip_ignores_forwarding_from_untrusted_peer() -> None:
    request = _client_request("203.0.113.9", [(b"x-forwarded-for", b"198.51.100.4")])
    settings = _settings(auth_trusted_proxy_networks="10.0.0.0/8")

    assert resolve_client_ip(request, settings) == "203.0.113.9"


def test_client_ip_resolves_rightmost_untrusted_hop_through_configured_proxies() -> None:
    request = _client_request(
        "10.0.0.3",
        [(b"x-forwarded-for", b"192.0.2.44, 198.51.100.8, 10.0.0.2")],
    )
    settings = _settings(
        auth_trusted_proxy_networks="10.0.0.0/8",
        auth_forwarded_ip_headers="x-forwarded-for",
    )

    assert resolve_client_ip(request, settings) == "198.51.100.8"


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("10.0.0.3", "for=192.0.2.44", "192.0.2.44"),
        ("2001:db8:ffff::2", 'for="[2001:db8::7]:443"', "2001:db8::7"),
    ],
)
def test_client_ip_validates_forwarded_ipv4_and_ipv6(peer: str, forwarded: str, expected: str) -> None:
    request = _client_request(peer, [(b"forwarded", forwarded.encode())])
    settings = _settings(
        auth_trusted_proxy_networks="10.0.0.0/8,2001:db8:ffff::/48",
        auth_forwarded_ip_headers="forwarded",
    )

    assert resolve_client_ip(request, settings) == expected


def test_client_ip_rejects_malformed_headers_and_invalid_configuration() -> None:
    malformed = _client_request("10.0.0.3", [(b"x-forwarded-for", b"client.example, arbitrary")])
    invalid_configuration = _settings(
        auth_trusted_proxy_networks="not-a-network",
        auth_forwarded_ip_headers="x-forwarded-for",
    )
    trusted_configuration = _settings(
        auth_trusted_proxy_networks="10.0.0.0/8",
        auth_forwarded_ip_headers="x-forwarded-for",
    )

    assert resolve_client_ip(malformed, trusted_configuration) == "10.0.0.3"
    assert resolve_client_ip(malformed, invalid_configuration) == "10.0.0.3"


def test_email_normalization_is_deterministic() -> None:
    assert normalize_email("  First.Last@EXAMPLE.COM  ") == "first.last@example.com"
    with pytest.raises(ValueError, match="invalid_email"):
        normalize_email("not-an-email")


def test_username_normalization_and_forced_password_gate() -> None:
    assert normalize_username("  Platform.Operator  ") == "platform.operator"
    with pytest.raises(ValueError, match="invalid_username"):
        normalize_username("not a username")
    principal = _principal(uuid.uuid4())
    principal.user.must_change_password = True
    with pytest.raises(HTTPException) as caught:
        require_full_access_principal(principal)
    assert caught.value.status_code == 403
    assert caught.value.detail == "password_change_required"


def test_platform_administrator_promotion_requires_username_argument() -> None:
    args = build_parser().parse_args(
        [
            "promote-platform-administrator",
            "--username",
            "existing-operator",
            "--platform-role",
            "reference-platform-operator",
            "--actor-reference",
            "reviewed-local-operator",
        ]
    )
    assert args.username == "existing-operator"
    assert args.platform_role == "reference-platform-operator"


def test_platform_identity_cli_requires_explicit_mode_and_password_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = build_parser().parse_args(
        [
            "provision-platform-identity",
            "--mode",
            "create",
            "--email",
            "operator@example.test",
            "--password-env",
            "PLATFORM_IDENTITY_TEST_PASSWORD",
            "--platform-role",
            "reference-platform-operator",
            "--actor-reference",
            "reviewed-local-operator",
        ]
    )
    monkeypatch.setenv("PLATFORM_IDENTITY_TEST_PASSWORD", "secret only in environment")

    assert args.mode == "create"
    assert args.platform_role == "reference-platform-operator"
    assert _password_from_environment(args.password_env, required=True) == "secret only in environment"
    with pytest.raises(ValueError, match="--password-env is required"):
        _password_from_environment(None, required=True)


def test_session_revocation_cli_is_preview_only_without_explicit_execute() -> None:
    user_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "revoke-auth-sessions",
            "--user-id",
            str(user_id),
            "--actor-reference",
            "reviewed-session-administrator",
        ]
    )
    assert args.user_id == user_id
    assert args.execute is False


def test_passwords_use_argon2id_and_allow_spaces() -> None:
    manager = PasswordManager(_settings())
    password_hash = manager.hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert manager.verify(password_hash, "correct horse battery staple").valid is True
    assert manager.verify(password_hash, "incorrect horse battery staple").valid is False
    assert "correct horse" not in password_hash


def test_default_password_minimum_is_fifteen_characters() -> None:
    assert Settings.model_fields["auth_password_min_length"].default == 15


def test_password_policy_enforces_configured_length_bounds_without_composition_rules() -> None:
    manager = PasswordManager(_settings(auth_password_min_length=15, auth_password_max_length=128))

    manager.validate_password("               ")
    manager.validate_password("entirely lowercase passphrase")
    manager.validate_password("frase única con espacios")
    with pytest.raises(PasswordPolicyError) as too_short:
        manager.validate_password("short")
    with pytest.raises(PasswordPolicyError) as too_long:
        manager.validate_password("x" * 129)

    assert too_short.value.code == "PASSWORD_TOO_SHORT"
    assert too_long.value.code == "PASSWORD_TOO_LONG"


def test_password_policy_rejects_common_passwords_with_stable_reason() -> None:
    manager = PasswordManager(_settings(auth_password_min_length=15))

    with pytest.raises(PasswordPolicyError) as captured:
        manager.validate_password("Password Password")

    assert captured.value.code == "PASSWORD_COMMON"


@pytest.mark.parametrize(
    ("password", "context"),
    [
        ("safe-admin@example.invalid-tail", PasswordContext(email="admin@example.invalid")),
        ("safe-operator-passphrase", PasswordContext(email="operator@example.invalid")),
        ("safe-patricia-passphrase", PasswordContext(display_name="Patricia Jones")),
        ("safe-acmerobotics-tail", PasswordContext(organization_name="Acme Robotics")),
        ("safe-acme-robotics-tail", PasswordContext(organization_slug="acme-robotics")),
        ("safe-sheku-passphrase", None),
    ],
)
def test_password_policy_rejects_identifiable_context(
    password: str,
    context: PasswordContext | None,
) -> None:
    manager = PasswordManager(_settings(auth_password_min_length=15))

    with pytest.raises(PasswordPolicyError) as captured:
        manager.validate_password(password, context=context)

    assert captured.value.code == "PASSWORD_CONTEXT_MATCH"


def test_obsolete_argon2_parameters_are_detected_for_rehash() -> None:
    old_hasher = PasswordHasher(
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )
    manager = PasswordManager(_settings(auth_argon2_time_cost=2, auth_argon2_hash_length=32))
    verification = manager.verify(old_hasher.hash("correct horse battery staple"), "correct horse battery staple")

    assert verification.valid is True
    assert verification.needs_rehash is True


def test_identity_database_cannot_equal_platform_database() -> None:
    database_url = "postgresql+psycopg://user:password@database/platform"
    with pytest.raises(ValidationError, match="must not point to the platform database"):
        Settings(database_url=database_url, identity_database_url=database_url)


def test_production_requires_explicit_identity_database_and_secure_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable_name in (
        "DATABASE_URL",
        "IDENTITY_DATABASE_URL",
        "AUTH_COOKIE_SECURE",
        "ENVIRONMENT_PROFILE",
        "APP_ENV",
        "ENVIRONMENT",
        "DEPLOYMENT_ENVIRONMENT",
    ):
        monkeypatch.delenv(variable_name, raising=False)

    with pytest.raises(ValidationError, match="IDENTITY_DATABASE_URL is required"):
        Settings(
            _env_file=None,
            ENVIRONMENT_PROFILE="production",
            auth_cookie_secure=True,
        )

    identity_database_url = "postgresql+psycopg://identity:secret@identity/identity"
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            ENVIRONMENT_PROFILE="production",
            identity_database_url=identity_database_url,
            auth_cookie_secure=False,
        )

    valid = Settings(
        _env_file=None,
        ENVIRONMENT_PROFILE="production",
        identity_database_url=identity_database_url,
        auth_cookie_secure=True,
    )

    assert valid.environment_profile == "production"
    assert valid.identity_database_url == identity_database_url
    assert valid.auth_cookie_secure is True


def test_runtime_context_uses_authenticated_identity_not_legacy_headers() -> None:
    organization_id = uuid.uuid4()
    principal = _principal(organization_id)
    request = _request(
        [
            (b"x-actor-reference", b"attacker-controlled"),
            (b"x-principal-type", b"service"),
        ]
    )
    authorization = MagicMock()
    authorization.resolve_permissions_for_scope.return_value = frozenset({"documents:read"})

    with patch(
        "app.api.dependencies.runtime_context.AuthorizationService",
        return_value=authorization,
    ):
        context = get_runtime_context(
            request=request,
            x_authorization_scope="organization",
            x_organization_id=organization_id,
            principal=principal,
            db=MagicMock(),
        )

    assert context.actor_reference == str(principal.user.id)
    assert context.organization_id == organization_id
    authorization.resolve_permissions_for_scope.assert_called_once_with(
        resource_scope=context.resource_scope,
        principal_id=str(principal.user.id),
        principal_type="user",
        allowed_role_ids=None,
    )
    signature = inspect.signature(get_runtime_context)
    assert "x_actor_reference" not in signature.parameters
    assert "x_principal_type" not in signature.parameters


def test_runtime_context_rejects_organization_without_active_membership() -> None:
    membership_organization = uuid.uuid4()
    requested_organization = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        get_runtime_context(
            request=_request(),
            x_authorization_scope="organization",
            x_organization_id=requested_organization,
            principal=_principal(membership_organization),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "organization_membership_required"


def test_platform_runtime_context_does_not_require_organization_membership_role() -> None:
    principal = _principal(uuid.uuid4())
    principal = AuthenticatedPrincipal(
        user=principal.user,
        session=principal.session,
        memberships=(),
    )
    authorization = MagicMock()
    authorization.resolve_permissions_for_scope.return_value = frozenset({"platform.operations:administer"})

    with patch(
        "app.api.dependencies.runtime_context.AuthorizationService",
        return_value=authorization,
    ):
        context = get_runtime_context(
            request=_request(),
            x_authorization_scope="platform",
            x_organization_id=None,
            principal=principal,
            db=MagicMock(),
        )

    assert context.has_permission("platform.operations", "administer")
    authorization.resolve_permissions_for_scope.assert_called_once_with(
        resource_scope=context.resource_scope,
        principal_id=str(principal.user.id),
        principal_type="user",
        allowed_role_ids=None,
    )


def test_session_secrets_are_one_way_hashes() -> None:
    token = "opaque-browser-token"
    token_hash = hash_secret(token)

    assert token_hash != token
    assert len(token_hash) == 64
    assert hash_secret(token) == token_hash


def test_identity_models_have_no_cross_database_foreign_keys() -> None:
    for table in (
        IdentityUser.__table__,
        OrganizationMembership.__table__,
        AuthSession.__table__,
    ):
        for foreign_key in table.foreign_keys:
            assert foreign_key.target_fullname.startswith("identity.")


def test_acceptance_provisioning_uses_governed_scope_permissions() -> None:
    assert required_permissions("/api/core/organizations", "POST") == frozenset(
        {"platform.organization_lifecycle:administer"}
    )
    assert required_permissions(
        "/api/security/management/global-users/user-1/memberships/organization-1",
        "PUT",
    ) == frozenset({"platform.security:administer"})
    assert required_permissions(
        "/api/security/management/global-users/runtime",
        "GET",
    ) == frozenset(
        {
            "platform.security:read",
            "platform.security:administer",
        }
    )
    assert required_permissions("/api/security/management/roles", "POST") == frozenset(
        {
            "organization.security:administer",
            "platform.security:administer",
        }
    )
    assert required_permissions("/api/security/management/roles", "GET") == frozenset(
        {
            "organization.security:read",
            "platform.security:read",
        }
    )


def test_every_functional_api_route_has_an_authorization_policy() -> None:
    unmapped = sorted(
        path for path in app.openapi()["paths"] if path.startswith("/api/") and not required_permissions(path, "GET")
    )

    assert unmapped == []


def test_platform_outage_does_not_invalidate_identity_session() -> None:
    organization_id = uuid.uuid4()
    principal = _principal(organization_id)

    def _identity_db():
        yield MagicMock()

    def _platform_unavailable():
        raise OperationalError("platform", {}, Exception("database unavailable"))
        yield

    app.dependency_overrides[get_authenticated_principal] = lambda: principal
    app.dependency_overrides[get_identity_db] = _identity_db
    app.dependency_overrides[get_db] = _platform_unavailable
    client = TestClient(app, raise_server_exceptions=False)
    try:
        functional = client.get(
            "/api/documents/document-types",
            headers={"X-Organization-ID": str(organization_id)},
        )
        identity = client.get("/auth/me")
    finally:
        client.close()
        app.dependency_overrides.pop(get_authenticated_principal, None)
        app.dependency_overrides.pop(get_identity_db, None)
        app.dependency_overrides.pop(get_db, None)

    assert functional.status_code == 503
    assert functional.json() == {"detail": "platform_service_unavailable"}
    assert identity.status_code == 200


def test_identity_outage_fails_closed_without_legacy_fallback() -> None:
    def _identity_unavailable():
        raise OperationalError("identity", {}, Exception("database unavailable"))
        yield

    app.dependency_overrides[get_identity_db] = _identity_unavailable
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/auth/login",
            headers={
                "X-Actor-Reference": "client-controlled",
                "X-Principal-Type": "user",
            },
            json={
                "email": "administrator@example.test",
                "password": "irrelevant password",
            },
        )
    finally:
        client.close()
        app.dependency_overrides.pop(get_identity_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "identity_service_unavailable"}
