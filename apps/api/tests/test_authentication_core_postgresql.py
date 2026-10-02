from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher, Type
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.identity.bootstrap import InitialAdminBootstrap, bootstrap_initial_admin
from app.identity.db import IdentityBase, get_identity_db
from app.identity.models import (
    AuthenticationEvent,
    AuthSession,
    IdentityUser,
    LoginThrottle,
    OrganizationMembership,
    PasswordCredential,
    SessionPolicy,
)
from app.identity.passwords import PasswordManager, PasswordPolicyError
from app.identity.platform_provisioning import (
    PlatformIdentityProvisioning,
    deactivate_platform_identity,
    provision_platform_identity,
)
from app.identity.service import IdentityService, hash_secret, normalize_email
from app.models.audit import AuditAction, AuditEvent, AuditHistory
from app.models.core import Organization
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.security.tenant_session import authorize_session_organization
from app.services.authorization import AuthorizationService
from main import app

TEST_IDENTITY_DATABASE_URL = os.getenv("TEST_IDENTITY_DATABASE_URL", "").strip()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_IDENTITY_DATABASE_URL,
    reason="TEST_IDENTITY_DATABASE_URL is required for Identity PostgreSQL integration tests",
)


@pytest.fixture(scope="module")
def identity_session_factory():
    parsed = make_url(TEST_IDENTITY_DATABASE_URL)
    if "test" not in str(parsed.database or "").lower():
        pytest.fail("TEST_IDENTITY_DATABASE_URL must target a dedicated test database")
    engine = create_engine(TEST_IDENTITY_DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
    IdentityBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def platform_session_factory():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for bootstrap integration")
    parsed = make_url(TEST_DATABASE_URL)
    if "test" not in str(parsed.database or "").lower():
        pytest.fail("TEST_DATABASE_URL must target a dedicated test database")
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS security"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            Role.__table__,
            Permission.__table__,
            RolePermission.__table__,
            RoleAssignment.__table__,
            Policy.__table__,
            AuditAction.__table__,
            AuditEvent.__table__,
            AuditHistory.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def identity_db(identity_session_factory):
    with identity_session_factory() as session:
        session.execute(
            text(
                "TRUNCATE TABLE "
                "identity.authentication_events, identity.auth_sessions, "
                "identity.login_throttles, identity.organization_memberships, "
                "identity.password_credentials, identity.users, identity.session_policies CASCADE"
            )
        )
        session.add(
            SessionPolicy(
                scope="platform",
                status="active",
                version=1,
                idle_timeout_seconds=1_800,
                absolute_timeout_seconds=28_800,
                max_concurrent_sessions=3,
                activity_write_interval_seconds=300,
                remember_me_enabled=False,
                remember_idle_timeout_seconds=86_400,
                remember_absolute_timeout_seconds=604_800,
                retention_days=90,
            )
        )
        session.commit()
        yield session


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://platform:unused@platform/platform_test",
        identity_database_url=TEST_IDENTITY_DATABASE_URL,
        auth_cookie_secure=False,
        auth_argon2_time_cost=2,
        auth_argon2_memory_cost_kib=8_192,
        auth_argon2_parallelism=1,
        auth_session_absolute_seconds=3_600,
        auth_session_inactivity_seconds=1_800,
        auth_session_touch_interval_seconds=60,
        auth_attempt_threshold=2,
        auth_attempt_block_base_seconds=30,
        auth_attempt_block_max_seconds=60,
    )


@pytest.fixture
def client(identity_session_factory, auth_settings):
    def _identity_dependency():
        with identity_session_factory() as session:
            yield session

    app.dependency_overrides[get_identity_db] = _identity_dependency
    app.dependency_overrides[get_settings] = lambda: auth_settings
    test_client = TestClient(app, base_url="http://testserver")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_identity_db, None)
        app.dependency_overrides.pop(get_settings, None)


def _seed_user(
    identity_db: Session,
    settings: Settings,
    *,
    email: str = "administrator@example.test",
    password: str = "correct horse battery staple",
    status_value: str = "active",
) -> tuple[IdentityUser, OrganizationMembership]:
    manager = PasswordManager(settings)
    user = IdentityUser(
        username="postgresql-user",
        email_normalized=normalize_email(email),
        email_display=email,
        display_name="Administrator",
        status=status_value,
        must_change_password=True,
    )
    identity_db.add(user)
    identity_db.flush()
    identity_db.add(
        PasswordCredential(
            user_id=user.id,
            password_hash=manager.hash_password(password),
            algorithm=manager.algorithm,
            parameters=manager.parameters,
        )
    )
    membership = OrganizationMembership(
        user_id=user.id,
        organization_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        status="active",
    )
    identity_db.add(membership)
    identity_db.commit()
    return user, membership


def _login(client: TestClient, email: str, password: str, *, remember_me: bool = False):
    return client.post(
        "/auth/login",
        json={"email": email, "password": password, "remember_me": remember_me},
    )


def _csrf(client: TestClient) -> str:
    response = client.get("/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _json_field_names(value: object) -> set[str]:
    if isinstance(value, dict):
        return {name for key, nested in value.items() for name in (str(key).lower(), *_json_field_names(nested))}
    if isinstance(value, list):
        return {name for nested in value for name in _json_field_names(nested)}
    return set()


def test_login_accepts_persisted_username(identity_db, auth_settings, client) -> None:
    password = "correct horse battery staple"
    user, _ = _seed_user(identity_db, auth_settings, password=password)

    response = _login(client, user.username.upper(), password)

    assert response.status_code == 200
    assert response.json()["user"]["username"] == user.username


def test_normalized_email_is_unique(identity_db, auth_settings) -> None:
    _seed_user(identity_db, auth_settings, email="Unique@Example.test")
    duplicate = IdentityUser(
        username="postgresql-user-duplicate",
        email_normalized=normalize_email(" unique@example.TEST "),
        email_display="unique@example.TEST",
        status="active",
        must_change_password=False,
    )
    identity_db.add(duplicate)
    with pytest.raises(IntegrityError):
        identity_db.commit()
    identity_db.rollback()


def test_login_cookie_and_session_token_persistence(identity_db, auth_settings, client, caplog) -> None:
    password = "correct horse battery staple"
    user, membership = _seed_user(identity_db, auth_settings, password=password)
    response = _login(client, " ADMINISTRATOR@example.test ", password)

    assert response.status_code == 200
    assert response.json()["user"]["username"] == user.username
    sensitive_fields = {
        "password",
        "password_hash",
        "token",
        "token_hash",
        "session_token",
        "csrf_token",
    }
    assert _json_field_names(response.json()).isdisjoint(sensitive_fields)
    assert password not in response.text
    assert str(membership.organization_id) in response.text
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    raw_token = client.cookies.get(auth_settings.auth_cookie_name)
    with identity_session_factory_from(identity_db)() as verification_db:
        persisted = verification_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert persisted is not None
        assert persisted.token_hash == hash_secret(raw_token)
        assert raw_token not in persisted.token_hash
    assert password not in caplog.text
    assert raw_token not in caplog.text


def identity_session_factory_from(session: Session):
    bind = session.get_bind()
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


def test_secure_cookie_setting_is_honored(identity_db, auth_settings, client) -> None:
    _seed_user(identity_db, auth_settings)
    secure_settings = auth_settings.model_copy(update={"auth_cookie_secure": True})
    app.dependency_overrides[get_settings] = lambda: secure_settings

    response = _login(client, "administrator@example.test", "correct horse battery staple")

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_wrong_and_unknown_accounts_have_same_response(identity_db, auth_settings, client) -> None:
    _seed_user(identity_db, auth_settings)
    wrong = _login(client, "administrator@example.test", "wrong password")
    unknown = _login(client, "unknown@example.test", "wrong password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid_email_or_password"}


def test_successful_login_rehashes_obsolete_parameters(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    credential = identity_db.get(PasswordCredential, user.id)
    old_hasher = PasswordHasher(
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )
    previous_hash = old_hasher.hash("correct horse battery staple")
    credential.password_hash = previous_hash
    credential.parameters = {"version": 0}
    identity_db.commit()

    response = _login(client, "administrator@example.test", "correct horse battery staple")

    assert response.status_code == 200
    identity_db.refresh(credential)
    assert credential.password_hash != previous_hash
    assert credential.password_hash.startswith("$argon2id$")
    assert credential.parameters["version"] == 1


def test_auth_me_does_not_require_platform_database(identity_db, auth_settings, client) -> None:
    _seed_user(identity_db, auth_settings)
    assert _login(client, "administrator@example.test", "correct horse battery staple").status_code == 200

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "administrator@example.test"
    assert response.json()["memberships"]


def test_forced_password_session_is_limited_until_change(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200

    assert client.get("/auth/me").status_code == 200
    assert client.get("/auth/csrf").status_code == 200
    blocked = client.get("/")
    assert blocked.status_code == 403
    assert blocked.json() == {"detail": "password_change_required"}

    csrf_token = _csrf(client)
    changed = client.post(
        "/auth/change-password",
        headers={auth_settings.auth_csrf_header_name: csrf_token},
        json={
            "current_password": "correct horse battery staple",
            "new_password": "new correct horse battery staple",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["reauthentication_required"] is True
    assert client.get("/").status_code == 401


def test_suspended_user_is_rejected_and_audited(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings, status_value="suspended")
    response = _login(client, "administrator@example.test", "correct horse battery staple")

    assert response.status_code == 401
    identity_db.expire_all()
    event = identity_db.scalar(
        select(AuthenticationEvent).where(
            AuthenticationEvent.user_id == user.id,
            AuthenticationEvent.event_type == "account_suspended_rejection",
        )
    )
    assert event is not None
    assert event.success is False


def test_persistent_attempt_limit_is_shared_through_identity_db(identity_db, auth_settings, client) -> None:
    _seed_user(identity_db, auth_settings)
    first = _login(client, "administrator@example.test", "wrong password")
    second = _login(client, "administrator@example.test", "wrong password")
    blocked = _login(client, "administrator@example.test", "correct horse battery staple")

    assert first.status_code == second.status_code == 401
    assert blocked.status_code == 429
    throttle = identity_db.scalar(select(LoginThrottle))
    assert throttle is not None
    assert throttle.failure_count == 2
    assert throttle.blocked_until is not None


def test_expired_session_is_rejected_and_persistently_revoked(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, "administrator@example.test", "correct horse battery staple").status_code == 200
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    auth_session.absolute_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    identity_db.commit()

    response = client.get("/auth/me")

    assert response.status_code == 401
    identity_db.refresh(auth_session)
    assert auth_session.revoked_at is not None
    assert auth_session.revocation_reason == "absolute_timeout"


def test_logout_is_csrf_protected_and_idempotent(identity_db, auth_settings, client) -> None:
    _seed_user(identity_db, auth_settings)
    assert _login(client, "administrator@example.test", "correct horse battery staple").status_code == 200
    rejected = client.post("/auth/logout")
    csrf_token = _csrf(client)
    first = client.post(
        "/auth/logout",
        headers={auth_settings.auth_csrf_header_name: csrf_token},
    )
    second = client.post("/auth/logout")

    assert rejected.status_code == 403
    assert first.status_code == second.status_code == 204
    assert client.cookies.get(auth_settings.auth_cookie_name) is None


def test_password_change_revokes_every_session_and_requires_new_login(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, "administrator@example.test", "correct horse battery staple").status_code == 200
    second_login = _login(client, "administrator@example.test", "correct horse battery staple")
    assert second_login.status_code == 200
    csrf_token = _csrf(client)

    response = client.post(
        "/auth/change-password",
        headers={auth_settings.auth_csrf_header_name: csrf_token},
        json={
            "current_password": "correct horse battery staple",
            "new_password": "a newer correct horse battery staple",
        },
    )

    assert response.status_code == 200
    assert client.cookies.get(auth_settings.auth_cookie_name) is None
    sessions = list(
        identity_db.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.created_at)
        ).all()
    )
    assert all(item.revoked_at is not None for item in sessions)
    assert all(item.revocation_reason == "password_changed" for item in sessions)
    identity_db.refresh(user)
    assert user.must_change_password is False


def test_persisted_platform_session_policy_has_governed_defaults(identity_db) -> None:
    policy = identity_db.scalar(select(SessionPolicy).where(SessionPolicy.scope == "platform"))
    assert policy is not None
    assert (
        policy.idle_timeout_seconds,
        policy.absolute_timeout_seconds,
        policy.max_concurrent_sessions,
        policy.activity_write_interval_seconds,
        policy.remember_me_enabled,
        policy.remember_idle_timeout_seconds,
        policy.remember_absolute_timeout_seconds,
        policy.retention_days,
    ) == (1_800, 28_800, 3, 300, False, 86_400, 604_800, 90)


def test_idle_expiration_is_persisted_and_rejected(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    auth_session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    identity_db.commit()
    assert client.get("/auth/me").status_code == 401
    identity_db.refresh(auth_session)
    assert auth_session.revocation_reason == "idle_timeout"


def test_activity_touch_extends_only_idle_deadline_and_is_throttled(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    policy = identity_db.scalar(select(SessionPolicy).where(SessionPolicy.scope == "platform"))
    assert policy is not None
    absolute = auth_session.absolute_expires_at
    auth_session.last_activity_at = datetime.now(UTC) - timedelta(
        seconds=policy.activity_write_interval_seconds + 1
    )
    auth_session.idle_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    identity_db.commit()
    assert client.get("/auth/me").status_code == 200
    identity_db.refresh(auth_session)
    touched_at = auth_session.last_activity_at
    assert auth_session.idle_expires_at > touched_at
    assert auth_session.absolute_expires_at == absolute
    assert client.get("/auth/me").status_code == 200
    identity_db.refresh(auth_session)
    assert auth_session.last_activity_at == touched_at
    assert (
        identity_db.scalar(
            select(AuthenticationEvent).where(
                AuthenticationEvent.session_id == auth_session.id,
                AuthenticationEvent.event_type == "session_activity_renewed",
            )
        )
        is not None
    )


def test_concurrent_session_limit_retains_newest_three(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    for _ in range(4):
        assert _login(client, user.username, "correct horse battery staple").status_code == 200
    sessions = list(
        identity_db.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.created_at, AuthSession.id)
        ).all()
    )
    active = [item for item in sessions if IdentityService.session_status(item) == "active"]
    assert len(active) == 3
    assert sessions[0].revocation_reason == "concurrent_session_limit"


def test_simultaneous_logins_never_exceed_persisted_limit(identity_db, identity_session_factory, auth_settings) -> None:
    user, _ = _seed_user(identity_db, auth_settings)

    def authenticate(index: int) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/auth/login",
                "headers": [(b"user-agent", f"concurrency-{index}".encode())],
                "client": ("127.0.0.1", 10_000 + index),
            }
        )
        with identity_session_factory() as concurrent_db:
            IdentityService(concurrent_db, auth_settings).authenticate(
                email=user.email_display,
                password="correct horse battery staple",
                request=request,
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(authenticate, range(4)))

    identity_db.expire_all()
    sessions = list(identity_db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all())
    assert sum(IdentityService.session_status(item) == "active" for item in sessions) == 3


def test_remember_me_is_ignored_while_disabled(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    response = _login(client, user.username, "correct horse battery staple", remember_me=True)
    assert response.status_code == 200
    assert "Max-Age" not in response.headers["set-cookie"]
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    assert auth_session.remember_me is False


def test_enabled_remember_me_uses_persisted_deadlines(identity_db, auth_settings, client) -> None:
    policy = identity_db.scalar(select(SessionPolicy).where(SessionPolicy.scope == "platform"))
    policy.remember_me_enabled = True
    identity_db.commit()
    user, _ = _seed_user(identity_db, auth_settings)
    response = _login(client, user.username, "correct horse battery staple", remember_me=True)
    assert response.status_code == 200
    assert "Max-Age" in response.headers["set-cookie"]
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    assert auth_session.remember_me is True
    assert auth_session.idle_expires_at == auth_session.created_at + timedelta(days=1)
    assert auth_session.absolute_expires_at == auth_session.created_at + timedelta(days=7)


def test_own_session_api_is_scoped_idempotent_and_does_not_expose_secrets(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    listed = client.get("/auth/sessions")
    assert listed.status_code == 200
    assert _json_field_names(listed.json()).isdisjoint({"token", "token_hash", "csrf_token_hash"})
    assert listed.json()["total"] == 1
    current = listed.json()["sessions"][0]
    assert current["current"] is True
    csrf_token = _csrf(client)
    unknown = client.delete(
        f"/auth/sessions/{uuid.uuid4()}",
        headers={auth_settings.auth_csrf_header_name: csrf_token},
    )
    assert unknown.status_code == 404
    revoked = client.delete(
        f"/auth/sessions/{current['id']}",
        headers={auth_settings.auth_csrf_header_name: csrf_token},
    )
    assert revoked.status_code == 204


def test_revoke_others_preserves_current_session(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    current_id = client.get("/auth/me").json()["session"]["id"]
    csrf_token = _csrf(client)
    assert (
        client.post(
            "/auth/sessions/revoke-others",
            headers={auth_settings.auth_csrf_header_name: csrf_token},
        ).status_code
        == 204
    )
    sessions = list(identity_db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all())
    assert next(item for item in sessions if str(item.id) == current_id).revoked_at is None
    assert all(item.revoked_at is not None for item in sessions if str(item.id) != current_id)


def test_session_history_is_filtered_paginated_and_current_first(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    for _ in range(4):
        assert _login(client, user.username, "correct horse battery staple").status_code == 200
    current_id = client.get("/auth/me").json()["session"]["id"]
    now = datetime.now(UTC)
    identity_db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_secret("expired-pagination-session"),
            created_at=now - timedelta(days=1),
            last_activity_at=now - timedelta(days=1),
            idle_expires_at=now - timedelta(hours=23),
            absolute_expires_at=now - timedelta(hours=22),
            idle_timeout_seconds=1_800,
            policy_version=1,
            remember_me=False,
            updated_at=now - timedelta(hours=22),
            metadata_json={},
        )
    )
    identity_db.commit()

    first_page = client.get("/auth/sessions?status=all&offset=0&limit=2")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 5
    assert len(first_page.json()["sessions"]) == 2
    assert first_page.json()["sessions"][0]["id"] == current_id
    assert first_page.json()["sessions"][0]["current"] is True

    active = client.get("/auth/sessions?status=active&offset=0&limit=10")
    revoked = client.get("/auth/sessions?status=revoked&offset=0&limit=10")
    expired = client.get("/auth/sessions?status=expired&offset=0&limit=10")
    assert active.json()["total"] == 3
    assert revoked.json()["total"] == 1
    assert expired.json()["total"] == 1
    assert _json_field_names(first_page.json()).isdisjoint({"token", "token_hash", "csrf_token_hash"})


def test_direct_session_revocation_is_idempotent(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    service = IdentityService(identity_db, auth_settings)
    assert service.revoke_session(auth_session, reason="self_revocation", user=user) is True
    assert service.revoke_session(auth_session, reason="self_revocation", user=user) is False
    identity_db.commit()
    events = list(
        identity_db.scalars(
            select(AuthenticationEvent).where(
                AuthenticationEvent.session_id == auth_session.id,
                AuthenticationEvent.reason_code == "self_revocation",
            )
        ).all()
    )
    assert len(events) == 1


def test_session_cleanup_respects_persisted_retention(identity_db, auth_settings) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    now = datetime.now(UTC)
    old = AuthSession(
        user_id=user.id,
        token_hash=hash_secret("historical-session"),
        created_at=now - timedelta(days=100),
        last_activity_at=now - timedelta(days=100),
        idle_expires_at=now - timedelta(days=99),
        absolute_expires_at=now - timedelta(days=99),
        idle_timeout_seconds=1_800,
        policy_version=1,
        revoked_at=now - timedelta(days=99),
        revocation_reason="logout",
        remember_me=False,
        updated_at=now - timedelta(days=99),
        metadata_json={},
    )
    identity_db.add(old)
    identity_db.commit()
    service = IdentityService(identity_db, auth_settings)
    assert service.purge_historical_sessions(execute=False) == 1
    assert identity_db.get(AuthSession, old.id) is not None
    assert service.purge_historical_sessions(execute=True) == 1
    assert identity_db.get(AuthSession, old.id) is None


def test_session_timestamps_are_utc_aware(identity_db, auth_settings, client) -> None:
    user, _ = _seed_user(identity_db, auth_settings)
    assert _login(client, user.username, "correct horse battery staple").status_code == 200
    auth_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    assert all(
        value.tzinfo is not None
        for value in (
            auth_session.created_at,
            auth_session.last_activity_at,
            auth_session.idle_expires_at,
            auth_session.absolute_expires_at,
        )
    )
    assert auth_session.idle_expires_at <= auth_session.absolute_expires_at


def test_global_session_administration_requires_persisted_permission_and_no_organization(
    identity_db, platform_session_factory, auth_settings, client
) -> None:
    user, membership = _seed_user(identity_db, auth_settings)
    identity_db.delete(membership)
    user.must_change_password = False
    identity_db.commit()
    with platform_session_factory() as platform_db:
        platform_db.execute(
            text(
                "TRUNCATE TABLE audit.audit_history, audit.audit_events, audit.audit_actions, "
                "security.role_assignments, security.policies, security.role_permissions, "
                "security.roles, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()

        def _platform_dependency():
            yield platform_db

        app.dependency_overrides[get_db] = _platform_dependency
        try:
            assert _login(client, user.username, "correct horse battery staple").status_code == 200
            headers = {"X-Authorization-Scope": "platform"}
            assert client.get("/api/platform/security/session-policy", headers=headers).status_code == 403

            role = Role(
                organization_id=None,
                code=f"session-administrator-{uuid.uuid4()}",
                name="Session Administrator",
                is_system=False,
                status="active",
                config={"scope": "platform"},
            )
            permissions = [
                Permission(
                    resource="platform.security",
                    action="administer",
                    description="administer",
                )
            ]
            platform_db.add_all([role, *permissions])
            platform_db.flush()
            now = datetime.now(UTC)
            platform_db.add_all(
                [
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                        created_at=now,
                        updated_at=now,
                    )
                    for permission in permissions
                ]
            )
            platform_db.add(
                RoleAssignment(
                    organization_id=None,
                    role_id=role.id,
                    principal_type="user",
                    principal_id=str(user.id),
                    scope_type="platform",
                    scope_id="platform",
                    status="active",
                    created_by="test",
                    updated_by="test",
                )
            )
            platform_db.commit()

            policy_response = client.get("/api/platform/security/session-policy", headers=headers)
            assert policy_response.status_code == 200
            users_response = client.get("/api/security/management/global-users/runtime", headers=headers)
            assert users_response.status_code == 200
            managed_user = next(
                item for item in users_response.json()["users"] if item["user_id"] == str(user.id)
            )
            assert managed_user["username"] == user.username
            assert managed_user["email"] == user.email_display
            roles_response = client.get("/api/security/management/global-roles", headers=headers)
            assert roles_response.status_code == 200
            assert any(item["role_id"] == str(role.id) for item in roles_response.json())
            before_deadline = identity_db.scalar(
                select(AuthSession.idle_expires_at).where(AuthSession.user_id == user.id)
            )
            csrf_token = _csrf(client)
            invalid = client.put(
                "/api/platform/security/session-policy",
                headers={**headers, auth_settings.auth_csrf_header_name: csrf_token},
                json={
                    "idle_timeout_seconds": 60,
                    "absolute_timeout_seconds": 3_600,
                    "max_concurrent_sessions": 1,
                    "activity_write_interval_seconds": 300,
                    "remember_me_enabled": False,
                    "remember_idle_timeout_seconds": 3_600,
                    "remember_absolute_timeout_seconds": 86_400,
                    "retention_days": 90,
                    "application_mode": "new_sessions_only",
                },
            )
            assert invalid.status_code == 422
            update = client.put(
                "/api/platform/security/session-policy",
                headers={**headers, auth_settings.auth_csrf_header_name: csrf_token},
                json={
                    "idle_timeout_seconds": 600,
                    "absolute_timeout_seconds": 3_600,
                    "max_concurrent_sessions": 1,
                    "activity_write_interval_seconds": 300,
                    "remember_me_enabled": False,
                    "remember_idle_timeout_seconds": 3_600,
                    "remember_absolute_timeout_seconds": 86_400,
                    "retention_days": 90,
                    "application_mode": "restrict_existing",
                },
            )
            assert update.status_code == 200
            identity_db.expire_all()
            managed_session = identity_db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
            assert managed_session.idle_expires_at <= before_deadline
            assert managed_session.idle_timeout_seconds == 600
            assert managed_session.policy_version == 2

            restricted_deadline = managed_session.idle_expires_at
            permissive_payload = {
                "idle_timeout_seconds": 1_800,
                "absolute_timeout_seconds": 28_800,
                "max_concurrent_sessions": 3,
                "activity_write_interval_seconds": 300,
                "remember_me_enabled": False,
                "remember_idle_timeout_seconds": 86_400,
                "remember_absolute_timeout_seconds": 604_800,
                "retention_days": 90,
                "application_mode": "new_sessions_only",
            }
            permissive = client.put(
                "/api/platform/security/session-policy",
                headers={**headers, auth_settings.auth_csrf_header_name: csrf_token},
                json=permissive_payload,
            )
            assert permissive.status_code == 200
            identity_db.refresh(managed_session)
            assert managed_session.idle_expires_at == restricted_deadline
            assert managed_session.idle_timeout_seconds == 600
            assert managed_session.policy_version == 2
            assert permissive.json()["version"] == 3
            repeated = client.put(
                "/api/platform/security/session-policy",
                headers={**headers, auth_settings.auth_csrf_header_name: csrf_token},
                json=permissive_payload,
            )
            assert repeated.status_code == 200
            assert repeated.json()["version"] == 3

            listed = client.get(
                f"/api/platform/security/users/{user.id}/sessions",
                headers=headers,
            )
            assert listed.status_code == 200
            assert listed.json()["total"] == 1
            assert listed.json()["limit"] == 10
            assert _json_field_names(listed.json()).isdisjoint({"token_hash", "csrf_token_hash"})
            revoked = client.delete(
                f"/api/platform/security/users/{user.id}/sessions/{managed_session.id}",
                headers={**headers, auth_settings.auth_csrf_header_name: csrf_token},
            )
            assert revoked.status_code == 200
            assert (
                platform_db.scalar(select(AuditEvent).where(AuditEvent.resource_type == "session_policy")) is not None
            )
            identity_audit = identity_db.scalar(
                select(AuthenticationEvent).where(AuthenticationEvent.event_type == "session_policy_updated")
            )
            assert identity_audit is not None
            assert identity_audit.actor_reference == str(user.id)
            assert identity_audit.metadata_json["application_mode"] in {
                "restrict_existing",
                "new_sessions_only",
            }
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_identity_unavailability_returns_service_unavailable(client) -> None:
    def _unavailable():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_service_unavailable",
        )
        yield

    app.dependency_overrides[get_identity_db] = _unavailable
    response = _login(client, "administrator@example.test", "irrelevant password")

    assert response.status_code == 503
    assert response.json() == {"detail": "identity_service_unavailable"}


def test_initial_admin_bootstrap_is_idempotent_across_both_databases(
    identity_db,
    platform_session_factory,
    auth_settings,
) -> None:
    with platform_session_factory() as platform_db:
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        organization = Organization(
            slug=f"bootstrap-{uuid.uuid4()}",
            name="Bootstrap Target",
            status="active",
            config={},
        )
        platform_db.add(organization)
        platform_db.flush()
        role = Role(
            organization_id=organization.id,
            code=f"administrator-{uuid.uuid4()}",
            name="Configured Administrator",
            is_system=False,
            status="active",
            config={},
        )
        platform_db.add(role)
        platform_db.flush()
        permission = Permission(
            resource="reference_tenant",
            action="administer",
            description="Bootstrap integration permission",
        )
        platform_db.add(permission)
        platform_db.flush()
        now = datetime.now(UTC)
        platform_db.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission.id,
                created_at=now,
                updated_at=now,
            )
        )
        platform_db.commit()
        command = InitialAdminBootstrap(
            email_display="initial.admin@example.test",
            display_name="Initial Administrator",
            password="correct horse battery staple",
            organization_id=organization.id,
            role_id=role.id,
        )

        first = bootstrap_initial_admin(identity_db, platform_db, auth_settings, command)
        second = bootstrap_initial_admin(identity_db, platform_db, auth_settings, command)

        assert first.user_id == second.user_id
        assert first.created_user is True
        assert second.created_user is False
        assert len(list(identity_db.scalars(select(IdentityUser)).all())) == 1
        assert len(list(identity_db.scalars(select(OrganizationMembership)).all())) == 1
        assert len(list(platform_db.scalars(select(RoleAssignment)).all())) == 1
        assert (
            identity_db.scalar(
                select(AuthenticationEvent).where(AuthenticationEvent.event_type == "bootstrap_admin_created")
            )
            is not None
        )


def test_platform_session_enforces_organization_query_boundary(
    platform_session_factory,
) -> None:
    with platform_session_factory() as setup_db:
        setup_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        setup_db.commit()
        first = Organization(
            slug=f"first-{uuid.uuid4()}",
            name="First Organization",
            status="active",
            config={},
        )
        second = Organization(
            slug=f"second-{uuid.uuid4()}",
            name="Second Organization",
            status="active",
            config={},
        )
        setup_db.add_all((first, second))
        setup_db.commit()

    with platform_session_factory() as scoped_db:
        authorize_session_organization(scoped_db, first.id)
        visible = list(scoped_db.scalars(select(Organization)).all())

    assert [item.id for item in visible] == [first.id]


def _seed_platform_role(platform_db: Session, *, system: bool = False) -> Role:
    role = Role(
        organization_id=None,
        code=f"platform-administrator-{uuid.uuid4()}",
        name="Platform Administrator",
        is_system=system,
        status="active",
        config={"scope": "platform"},
    )
    permission = Permission(
        resource="platform.operations",
        action="administer",
        description="Platform operations administration",
    )
    platform_db.add_all((role, permission))
    platform_db.flush()
    now = datetime.now(UTC)
    platform_db.add(
        RolePermission(
            role_id=role.id,
            permission_id=permission.id,
            created_at=now,
            updated_at=now,
        )
    )
    platform_db.commit()
    return role


def test_platform_authority_extends_to_an_explicitly_joined_organization(
    platform_session_factory,
) -> None:
    principal_id = str(uuid.uuid4())
    with platform_session_factory() as platform_db:
        platform_db.execute(text("TRUNCATE TABLE audit.audit_events, audit.audit_actions CASCADE"))
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        organization = Organization(
            slug=f"joined-{uuid.uuid4()}",
            name="Joined Organization",
            status="active",
            config={},
        )
        platform_db.add(organization)
        platform_db.flush()
        platform_role = _seed_platform_role(platform_db)
        platform_db.add(
            RoleAssignment(
                organization_id=None,
                role_id=platform_role.id,
                principal_type="user",
                principal_id=principal_id,
                scope_type="platform",
                scope_id="platform",
                status="active",
            )
        )
        platform_db.commit()

        permissions = AuthorizationService(platform_db).resolve_permissions(
            principal_id=principal_id,
            organization_id=organization.id,
            scope_type="organization",
        )

    assert "platform.operations:administer" in permissions


def test_platform_identity_provisioning_creates_second_authenticable_global_admin(
    identity_db,
    platform_session_factory,
    auth_settings,
    client,
) -> None:
    restricted_user, _ = _seed_user(
        identity_db,
        auth_settings,
        email="restricted@example.test",
    )
    restricted_user.must_change_password = False
    identity_db.commit()
    password = "a governed platform password"
    with platform_session_factory() as platform_db:
        platform_db.execute(text("TRUNCATE TABLE audit.audit_events, audit.audit_actions CASCADE"))
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        role = _seed_platform_role(platform_db)

        result = provision_platform_identity(
            identity_db,
            platform_db,
            auth_settings,
            PlatformIdentityProvisioning(
                mode="create",
                email_display="platform.admin@example.test",
                display_name="Platform Administrator",
                password=password,
                platform_role_reference=str(role.id),
                actor_reference="operator-reviewed-change",
            ),
        )

        credential = identity_db.get(PasswordCredential, result.user_id)
        user = identity_db.get(IdentityUser, result.user_id)
        assert credential is not None
        assert credential.password_hash.startswith("$argon2id$")
        assert password not in credential.password_hash
        assert PasswordManager(auth_settings).verify(credential.password_hash, password).valid
        assert user.must_change_password is True
        assert not list(
            identity_db.scalars(select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)).all()
        )
        assert _login(client, "platform.admin@example.test", password).status_code == 200

        permissions = AuthorizationService(platform_db).resolve_permissions(
            principal_id=str(user.id),
            scope_type="platform",
        )
        assert "platform.operations:administer" in permissions
        assignment = platform_db.get(RoleAssignment, result.assignment_id)
        assert assignment.organization_id is None
        assert assignment.scope_type == assignment.scope_id == "platform"
        audit = platform_db.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_type == "platform_identity",
                AuditEvent.resource_id == str(user.id),
            )
        )
        assert audit is not None
        assert audit.actor_id == "operator-reviewed-change"
        assert audit.metadata_json["result"] == "succeeded"
        serialized_audit = str(audit.metadata_json)
        assert password not in serialized_audit
        assert credential.password_hash not in serialized_audit

        restricted_permissions = AuthorizationService(platform_db).resolve_permissions(
            principal_id=str(restricted_user.id),
            scope_type="platform",
        )
        assert "platform.operations:administer" not in restricted_permissions

        def _platform_dependency():
            yield platform_db

        app.dependency_overrides[get_db] = _platform_dependency
        try:
            client.cookies.clear()
            assert (
                _login(
                    client,
                    "restricted@example.test",
                    "correct horse battery staple",
                ).status_code
                == 200
            )
            csrf_token = _csrf(client)
            rejected = client.post(
                "/api/platform/operations/components",
                headers={
                    "X-Authorization-Scope": "platform",
                    auth_settings.auth_csrf_header_name: csrf_token,
                },
                json={
                    "scope": "platform",
                    "component_code": "authorization-probe",
                    "component_type": "test",
                    "instance_id": "restricted-identity",
                    "display_name": "Restricted identity authorization probe",
                },
            )
            assert rejected.status_code == 403
            assert rejected.json() == {"detail": "permission_required"}
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_platform_identity_provisioning_requires_explicit_deterministic_update(
    identity_db,
    platform_session_factory,
    auth_settings,
) -> None:
    with platform_session_factory() as platform_db:
        platform_db.execute(text("TRUNCATE TABLE audit.audit_events, audit.audit_actions CASCADE"))
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        role = _seed_platform_role(platform_db)
        create = PlatformIdentityProvisioning(
            mode="create",
            email_display="repeatable@example.test",
            display_name="Original Name",
            password="original governed password",
            platform_role_reference=role.code,
            actor_reference="first-operator",
        )
        first = provision_platform_identity(identity_db, platform_db, auth_settings, create)
        original_hash = identity_db.get(PasswordCredential, first.user_id).password_hash

        with pytest.raises(ValueError, match="explicit update mode"):
            provision_platform_identity(identity_db, platform_db, auth_settings, create)
        identity_db.rollback()
        platform_db.rollback()
        assert identity_db.get(PasswordCredential, first.user_id).password_hash == original_hash
        assert (
            len(
                list(
                    platform_db.scalars(
                        select(RoleAssignment).where(RoleAssignment.principal_id == str(first.user_id))
                    ).all()
                )
            )
            == 1
        )

        unchanged = provision_platform_identity(
            identity_db,
            platform_db,
            auth_settings,
            PlatformIdentityProvisioning(
                mode="update",
                email_display="repeatable@example.test",
                display_name=None,
                password=None,
                platform_role_reference=role.code,
                actor_reference="second-operator",
            ),
        )
        assert unchanged.user_id == first.user_id
        assert unchanged.changed_fields == ()
        assert identity_db.get(PasswordCredential, first.user_id).password_hash == original_hash

        updated = provision_platform_identity(
            identity_db,
            platform_db,
            auth_settings,
            PlatformIdentityProvisioning(
                mode="update",
                email_display="repeatable@example.test",
                display_name="Updated Name",
                password="replacement governed password",
                platform_role_reference=role.code,
                actor_reference="second-operator",
            ),
        )
        assert updated.changed_fields == ("display_name", "password_credential")
        assert identity_db.get(IdentityUser, first.user_id).display_name == "Updated Name"
        assert identity_db.get(PasswordCredential, first.user_id).password_hash != original_hash


def test_platform_identity_provisioning_rejects_invalid_inputs_and_non_delegable_role(
    identity_db,
    platform_session_factory,
    auth_settings,
) -> None:
    with platform_session_factory() as platform_db:
        platform_db.execute(text("TRUNCATE TABLE audit.audit_events, audit.audit_actions CASCADE"))
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        system_role = _seed_platform_role(platform_db, system=True)
        base = dict(
            mode="create",
            email_display="invalid@example.test",
            display_name=None,
            actor_reference="reviewed-operator",
        )
        with pytest.raises(ValueError, match="does not exist"):
            provision_platform_identity(
                identity_db,
                platform_db,
                auth_settings,
                PlatformIdentityProvisioning(
                    **base,
                    password="valid governed password",
                    platform_role_reference=str(uuid.uuid4()),
                ),
            )
        identity_db.rollback()
        platform_db.rollback()
        with pytest.raises(ValueError, match="not delegable"):
            provision_platform_identity(
                identity_db,
                platform_db,
                auth_settings,
                PlatformIdentityProvisioning(
                    **base,
                    password="valid governed password",
                    platform_role_reference=str(system_role.id),
                ),
            )
        identity_db.rollback()
        platform_db.rollback()
        system_role.is_system = False
        platform_db.commit()
        with pytest.raises(PasswordPolicyError):
            provision_platform_identity(
                identity_db,
                platform_db,
                auth_settings,
                PlatformIdentityProvisioning(
                    **base,
                    password="short",
                    platform_role_reference=str(system_role.id),
                ),
            )


def test_platform_identity_deactivation_is_safe_and_idempotent(
    identity_db,
    platform_session_factory,
    auth_settings,
) -> None:
    with platform_session_factory() as platform_db:
        platform_db.execute(text("TRUNCATE TABLE audit.audit_events, audit.audit_actions CASCADE"))
        platform_db.execute(
            text(
                "TRUNCATE TABLE security.role_assignments, security.policies, security.roles, "
                "security.role_permissions, security.permissions, core.organizations CASCADE"
            )
        )
        platform_db.commit()
        role = _seed_platform_role(platform_db)
        created = provision_platform_identity(
            identity_db,
            platform_db,
            auth_settings,
            PlatformIdentityProvisioning(
                mode="create",
                email_display="deactivate@example.test",
                display_name=None,
                password="valid governed password",
                platform_role_reference=role.code,
                actor_reference="creator",
            ),
        )
        first = deactivate_platform_identity(
            identity_db,
            platform_db,
            email="deactivate@example.test",
            platform_role_reference=role.code,
            actor_reference="deactivator",
        )
        second = deactivate_platform_identity(
            identity_db,
            platform_db,
            email="deactivate@example.test",
            platform_role_reference=role.code,
            actor_reference="deactivator",
        )

        assert first.user_id == second.user_id == created.user_id
        assert second.changed_fields == ()
        assert identity_db.get(IdentityUser, created.user_id).status == "suspended"
        assert platform_db.get(RoleAssignment, created.assignment_id).status == "inactive"
