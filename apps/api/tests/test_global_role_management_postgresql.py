from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.audit import AuditAction, AuditEvent, AuditHistory
from app.models.core import Organization
from app.models.security import Permission, Role, RolePermission
from app.services.security_management import GlobalRoleManagementError, GlobalRoleManagementService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for global role PostgreSQL integration tests",
)


@pytest.fixture(scope="module")
def platform_session_factory():
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
def db(platform_session_factory):
    with platform_session_factory() as session:
        session.execute(
            text(
                "TRUNCATE TABLE audit.audit_history, audit.audit_events, "
                "security.role_permissions, security.roles, security.permissions CASCADE"
            )
        )
        session.commit()
        yield session


def _seed_permissions(db) -> None:
    db.add_all(
        [
            Permission(resource="platform.operations", action="read", description="Read operations."),
            Permission(resource="platform.security", action="read", description="Read security."),
        ]
    )
    db.commit()


def _service(db) -> GlobalRoleManagementService:
    return GlobalRoleManagementService(
        db,
        actor_reference="global-role-test-actor",
        correlation_id="global-role-test-correlation",
    )


def test_reconcile_is_atomic_and_idempotent(db) -> None:
    _seed_permissions(db)
    specification = {
        "code": "configurable-reader",
        "name": "Configurable Reader",
        "description": "Configurable platform reader.",
        "permission_keys": ["platform.security:read", "platform.operations:read"],
    }

    created = _service(db).reconcile(**specification)
    repeated = _service(db).reconcile(**specification)

    assert created["outcome"] == "created"
    assert repeated["outcome"] == "idempotent"
    assert repeated["role_id"] == created["role_id"]
    assert repeated["permission_keys"] == sorted(specification["permission_keys"])
    assert db.scalar(select(func.count(Role.id))) == 1
    assert db.scalar(select(func.count(RolePermission.id))) == 2
    assert db.scalar(select(func.count(AuditEvent.id))) == 2
    assert db.scalar(select(func.count(AuditHistory.id))) == 2


def test_conflicting_specification_is_rejected_and_audited(db) -> None:
    _seed_permissions(db)
    _service(db).reconcile(
        code="configurable-reader",
        name="Configurable Reader",
        description=None,
        permission_keys=["platform.operations:read"],
    )

    with pytest.raises(GlobalRoleManagementError) as caught:
        _service(db).reconcile(
            code="configurable-reader",
            name="Different Name",
            description=None,
            permission_keys=["platform.operations:read"],
        )

    assert caught.value.status_code == 409
    assert caught.value.code == "global_role_specification_conflict"
    assert db.scalar(select(func.count(Role.id))) == 1
    assert db.scalar(select(func.count(RolePermission.id))) == 1
    assert db.scalar(select(func.count(AuditEvent.id))) == 2


def test_unknown_permission_leaves_no_role_or_association(db) -> None:
    _seed_permissions(db)

    with pytest.raises(GlobalRoleManagementError) as caught:
        _service(db).reconcile(
            code="unknown-permission-reader",
            name="Unknown Permission Reader",
            description=None,
            permission_keys=["platform.unknown:read"],
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "unknown_permission"
    assert db.scalar(select(func.count(Role.id))) == 0
    assert db.scalar(select(func.count(RolePermission.id))) == 0
    assert db.scalar(select(func.count(AuditEvent.id))) == 1


def test_status_transitions_are_idempotent_and_preserve_permissions(db) -> None:
    _seed_permissions(db)
    service = _service(db)
    service.reconcile(
        code="configurable-reader",
        name="Configurable Reader",
        description=None,
        permission_keys=["platform.operations:read"],
    )

    deactivated = _service(db).deactivate("configurable-reader")
    repeated = _service(db).deactivate("configurable-reader")
    activated = _service(db).activate("configurable-reader")

    assert deactivated["outcome"] == "updated"
    assert repeated["outcome"] == "idempotent"
    assert activated["outcome"] == "updated"
    assert activated["status"] == "active"
    assert activated["permission_keys"] == ["platform.operations:read"]
    assert db.scalar(select(func.count(RolePermission.id))) == 1


@pytest.mark.parametrize("is_system", [False, True])
def test_catalog_includes_every_persisted_platform_role_regardless_of_system_flag(db, is_system: bool) -> None:
    _seed_permissions(db)
    role = Role(
        organization_id=None,
        code=f"persisted-platform-role-{str(is_system).lower()}",
        name="Persisted Platform Role",
        status="active",
        is_system=is_system,
        config={"scope": "platform"},
    )
    db.add(role)
    db.flush()
    permission = db.scalar(select(Permission).where(Permission.resource == "platform.operations"))
    now = datetime.now(UTC)
    db.add(
        RolePermission(
            role_id=role.id,
            permission_id=permission.id,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    catalog = _service(db).list_roles()

    assert len(catalog) == 1
    assert catalog[0]["role_id"] == str(role.id)
    assert catalog[0]["permission_keys"] == ["platform.operations:read"]
    assert catalog[0]["configurable"] is False
