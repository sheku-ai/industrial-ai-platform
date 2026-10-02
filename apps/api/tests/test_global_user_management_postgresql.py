from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.identity.base import IdentityBase
from app.identity.models import AuthSession, IdentityUser, OrganizationMembership, PasswordCredential
from app.identity.platform_provisioning import promote_platform_administrator
from app.models.audit import AuditEvent, AuditHistory
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission
from app.schemas.security_management import GlobalUserRead
from app.services.global_user_management import GlobalUserManagementError, GlobalUserManagementService

TEST_IDENTITY_DATABASE_URL = os.getenv("TEST_IDENTITY_DATABASE_URL", "").strip()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_IDENTITY_DATABASE_URL or not TEST_DATABASE_URL, reason="Both PostgreSQL test database URLs are required"
)


@pytest.fixture(scope="module")
def factories():
    for value in (TEST_IDENTITY_DATABASE_URL, TEST_DATABASE_URL):
        if "test" not in str(make_url(value).database or "").lower():
            pytest.fail("Global user integration tests require dedicated test databases")
    identity_engine = create_engine(TEST_IDENTITY_DATABASE_URL)
    platform_engine = create_engine(TEST_DATABASE_URL)
    with identity_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
    with platform_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS security"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
    IdentityBase.metadata.create_all(identity_engine)
    Base.metadata.create_all(
        platform_engine,
        tables=[
            Organization.__table__,
            Role.__table__,
            Permission.__table__,
            RolePermission.__table__,
            RoleAssignment.__table__,
            AuditEvent.__table__,
            AuditHistory.__table__,
        ],
    )
    yield (
        sessionmaker(bind=identity_engine, expire_on_commit=False),
        sessionmaker(bind=platform_engine, expire_on_commit=False),
    )
    identity_engine.dispose()
    platform_engine.dispose()


@pytest.fixture
def databases(factories):
    identity_factory, platform_factory = factories
    with identity_factory() as identity_db, platform_factory() as platform_db:
        identity_db.execute(
            text(
                "TRUNCATE TABLE identity.authentication_events, identity.auth_sessions, "
                "identity.login_throttles, identity.organization_memberships, "
                "identity.password_credentials, identity.users CASCADE"
            )
        )
        platform_db.execute(
            text(
                "TRUNCATE TABLE audit.audit_history, audit.audit_events, security.role_assignments, "
                "security.role_permissions, security.roles, security.permissions, core.organizations CASCADE"
            )
        )
        identity_db.commit()
        platform_db.commit()
        yield identity_db, platform_db


@pytest.fixture
def settings() -> Settings:
    return Settings(
        identity_database_url=TEST_IDENTITY_DATABASE_URL,
        database_url=TEST_DATABASE_URL,
        auth_argon2_time_cost=2,
        auth_argon2_memory_cost_kib=8_192,
        auth_argon2_parallelism=1,
    )


def _catalog(platform_db):
    organization_a = Organization(slug="organization-a", name="Organization A", status="active")
    organization_b = Organization(slug="organization-b", name="Organization B", status="active")
    permission = Permission(resource="platform.security", action="administer")
    global_role = Role(
        organization_id=None,
        code="platform-administrator",
        name="Platform Administrator",
        status="active",
        is_system=False,
        config={"scope": "platform"},
    )
    platform_db.add_all([organization_a, organization_b, permission, global_role])
    platform_db.flush()
    role_a = Role(
        organization_id=organization_a.id,
        code="organization-a-reader",
        name="Organization A Reader",
        status="active",
        is_system=False,
        config={},
    )
    role_b = Role(
        organization_id=organization_b.id,
        code="organization-b-reader",
        name="Organization B Reader",
        status="active",
        is_system=False,
        config={},
    )
    platform_db.add_all([role_a, role_b])
    platform_db.flush()
    now = datetime.now(UTC)
    platform_db.add(RolePermission(role_id=global_role.id, permission_id=permission.id, created_at=now, updated_at=now))
    platform_db.commit()
    return organization_a, organization_b, global_role, role_a, role_b


def _service(identity_db, platform_db, settings, actor_id=None):
    return GlobalUserManagementService(
        identity_db,
        platform_db,
        settings,
        actor_reference=str(actor_id or uuid.uuid4()),
        correlation_id="global-user-test",
    )


def test_create_edit_reset_and_revoke_are_persisted_and_secret_free(databases, settings) -> None:
    identity_db, platform_db = databases
    created = _service(identity_db, platform_db, settings).create(
        username="runtime-reader",
        display_name="Runtime Reader",
        email="reader@example.test",
        temporary_password="correct horse battery staple",
    )
    user_id = created["user"]["user_id"]
    user = identity_db.get(IdentityUser, user_id)
    credential = identity_db.get(PasswordCredential, user_id)
    assert user.must_change_password is True and credential.algorithm == "argon2id"
    assert "correct horse battery staple" not in credential.password_hash
    assert (
        _service(identity_db, platform_db, settings).update(user_id, {"display_name": "Updated Reader"})["user"][
            "display_name"
        ]
        == "Updated Reader"
    )
    now = datetime.now(UTC)
    session = AuthSession(
        user_id=user_id,
        token_hash="a" * 64,
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
    identity_db.add(session)
    identity_db.commit()
    _service(identity_db, platform_db, settings).reset_password(user_id, "another correct horse battery staple")
    assert identity_db.get(AuthSession, session.id).revoked_at is not None
    audit_payload = " ".join(str(item.metadata_json) for item in platform_db.scalars(select(AuditEvent)).all())
    assert "correct horse battery staple" not in audit_payload


def test_global_and_organization_assignments_remain_separate(databases, settings) -> None:
    identity_db, platform_db = databases
    organization_a, organization_b, global_role, role_a, role_b = _catalog(platform_db)
    user_id = _service(identity_db, platform_db, settings).create(
        username="scoped-user",
        display_name="Scoped User",
        email="scoped@example.test",
        temporary_password="correct horse battery staple",
    )["user"]["user_id"]
    service = _service(identity_db, platform_db, settings)
    service.set_role(user_id, global_role.id, None, True)
    service.set_membership(user_id, organization_a.id, role_a.id, True)
    with pytest.raises(GlobalUserManagementError, match="organization_membership_required"):
        service.set_role(user_id, role_b.id, organization_b.id, True)
    assert identity_db.scalar(select(func.count(OrganizationMembership.id))) == 1
    assignments = platform_db.scalars(
        select(RoleAssignment).where(RoleAssignment.principal_id == str(user_id), RoleAssignment.status == "active")
    ).all()
    assert {(item.scope_type, item.organization_id) for item in assignments} == {
        ("platform", None),
        ("organization", organization_a.id),
    }
    service.set_membership(user_id, organization_a.id, None, False)
    assert (
        platform_db.scalar(
            select(func.count(RoleAssignment.id)).where(
                RoleAssignment.organization_id == organization_a.id, RoleAssignment.status == "active"
            )
        )
        == 0
    )


def test_runtime_hydrates_identity_fields_and_reconciles_platform_role_catalog(databases, settings) -> None:
    identity_db, platform_db = databases
    _, _, global_role, _, _ = _catalog(platform_db)
    service = _service(identity_db, platform_db, settings)
    user_id = service.create(
        username="hydrated-user",
        display_name="Hydrated User",
        email="hydrated@example.test",
        temporary_password="correct horse battery staple",
    )["user"]["user_id"]
    service.set_role(user_id, global_role.id, None, True)

    runtime = service.runtime()
    user = next(item for item in runtime["users"] if item["user_id"] == user_id)
    catalog_role = next(item for item in runtime["global_roles"] if item["role_id"] == global_role.id)

    assert (user["username"], user["display_name"], user["email"]) == (
        "hydrated-user",
        "Hydrated User",
        "hydrated@example.test",
    )
    serialized = GlobalUserRead.model_validate(user).model_dump(mode="json")
    assert serialized["username"] == "hydrated-user"
    assert serialized["email"] == "hydrated@example.test"
    assert serialized["username"] and serialized["email"]
    assert user["global_roles"][0]["role_id"] == catalog_role["role_id"]
    assert user["global_roles"][0]["available"] is True
    assert catalog_role["permission_keys"] == ["platform.security:administer"]


def test_unavailable_assigned_platform_role_is_reported_explicitly(databases, settings) -> None:
    identity_db, platform_db = databases
    _, _, global_role, _, _ = _catalog(platform_db)
    service = _service(identity_db, platform_db, settings)
    user_id = service.create(
        username="inconsistent-user",
        display_name="Inconsistent User",
        email="inconsistent@example.test",
        temporary_password="correct horse battery staple",
    )["user"]["user_id"]
    service.set_role(user_id, global_role.id, None, True)
    global_role.status = "inactive"
    platform_db.commit()

    assigned = service.runtime()["users"][0]["global_roles"][0]

    assert assigned["available"] is False
    assert assigned["inconsistency"] == "assigned_role_not_available"


def test_last_global_administrator_cannot_lose_access(databases, settings) -> None:
    identity_db, platform_db = databases
    _, _, global_role, _, _ = _catalog(platform_db)
    user_id = _service(identity_db, platform_db, settings).create(
        username="sole-admin",
        display_name="Sole Admin",
        email="admin@example.test",
        temporary_password="correct horse battery staple",
    )["user"]["user_id"]
    service = _service(identity_db, platform_db, settings, user_id)
    service.set_role(user_id, global_role.id, None, True)
    with pytest.raises(GlobalUserManagementError, match="last_global_administrator_required"):
        service.set_status(user_id, False)
    with pytest.raises(GlobalUserManagementError, match="last_global_administrator_required"):
        service.set_role(user_id, global_role.id, None, False)


def test_safe_delete_allows_unreferenced_identity_and_rejects_dependencies(databases, settings) -> None:
    identity_db, platform_db = databases
    unreferenced = IdentityUser(
        username="unreferenced",
        email_normalized="unreferenced@example.test",
        email_display="unreferenced@example.test",
        display_name="Unreferenced",
        status="active",
        must_change_password=False,
    )
    referenced = IdentityUser(
        username="referenced",
        email_normalized="referenced@example.test",
        email_display="referenced@example.test",
        display_name="Referenced",
        status="active",
        must_change_password=False,
    )
    identity_db.add_all([unreferenced, referenced])
    identity_db.flush()
    identity_db.add(
        OrganizationMembership(
            user_id=referenced.id, organization_id=uuid.uuid4(), role_id=uuid.uuid4(), status="active"
        )
    )
    identity_db.commit()
    deleted_id = unreferenced.id
    assert _service(identity_db, platform_db, settings).delete(deleted_id)["outcome"] == "deleted"
    assert identity_db.get(IdentityUser, deleted_id) is None
    with pytest.raises(GlobalUserManagementError, match="identity_has_dependencies_deactivate_instead"):
        _service(identity_db, platform_db, settings).delete(referenced.id)


def test_administrator_promotion_is_idempotent_and_username_driven(databases) -> None:
    identity_db, platform_db = databases
    _, _, global_role, _, _ = _catalog(platform_db)
    user = IdentityUser(
        username="promotable",
        email_normalized="promotable@example.test",
        email_display="promotable@example.test",
        display_name="Promotable",
        status="active",
        must_change_password=False,
    )
    identity_db.add(user)
    identity_db.commit()
    first = promote_platform_administrator(
        identity_db,
        platform_db,
        username="promotable",
        platform_role_reference=global_role.code,
        actor_reference="test-provisioner",
    )
    second = promote_platform_administrator(
        identity_db,
        platform_db,
        username="promotable",
        platform_role_reference=global_role.code,
        actor_reference="test-provisioner",
    )
    assert first.assignment_id == second.assignment_id
    assert first.changed_fields == ("platform_role_assignment",) and second.changed_fields == ()
