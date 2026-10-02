from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.cli.__main__ import build_parser
from app.identity.installation_bootstrap import (
    INSTALLATION_ADMIN_PERMISSION_CATALOG,
    InstallationBootstrap,
    _get_or_create_organization,
    _normalize_inputs,
)
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission
from app.security.platform_roles import (
    PLATFORM_ADMIN_PERMISSION_CATALOG,
    PLATFORM_OWNER_ROLE_CODE,
    reconcile_platform_owner_assignment,
    reconcile_platform_owner_role,
)


class _OrganizationSession:
    def __init__(self, existing: Organization | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flushes = 0

    def scalar(self, _statement):
        return self.existing

    def add(self, record: object) -> None:
        self.added.append(record)
        if isinstance(record, Organization) and record.id is None:
            record.id = uuid.uuid4()

    def flush(self) -> None:
        self.flushes += 1


class _PlatformAuthoritySession:
    def __init__(self) -> None:
        self.roles: list[Role] = []
        self.permissions: list[Permission] = []
        self.role_permissions: list[RolePermission] = []
        self.assignments: list[RoleAssignment] = []

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        parameters = set(statement.compile().params.values())
        if entity is Role:
            return self.roles[0] if self.roles else None
        if entity is Permission:
            return next(
                (
                    permission
                    for permission in self.permissions
                    if permission.resource in parameters and permission.action in parameters
                ),
                None,
            )
        if entity is RolePermission:
            return next(
                (
                    link
                    for link in self.role_permissions
                    if link.role_id in parameters and link.permission_id in parameters
                ),
                None,
            )
        if entity is RoleAssignment:
            return self.assignments[0] if self.assignments else None
        raise AssertionError(f"unexpected select entity: {entity}")

    def add(self, record: object) -> None:
        if isinstance(record, Role) and record not in self.roles:
            self.roles.append(record)
        elif isinstance(record, Permission) and record not in self.permissions:
            self.permissions.append(record)
        elif isinstance(record, RolePermission) and record not in self.role_permissions:
            self.role_permissions.append(record)
        elif isinstance(record, RoleAssignment) and record not in self.assignments:
            self.assignments.append(record)

    def flush(self) -> None:
        for record in [*self.roles, *self.permissions, *self.role_permissions, *self.assignments]:
            if record.id is None:
                record.id = uuid.uuid4()


def _command(
    *,
    name: str = "Example Organization",
    slug: str = "example-organization",
) -> InstallationBootstrap:
    return InstallationBootstrap(
        organization_name=name,
        organization_slug=slug,
        admin_email="admin@example.invalid",
        admin_display_name="Administrator",
        admin_password="not-used-by-this-test",
    )


def test_installation_inputs_accept_generic_configurable_organization() -> None:
    assert _normalize_inputs(_command()) == (
        "Example Organization",
        "example-organization",
    )


def test_installation_inputs_reject_invalid_slug() -> None:
    with pytest.raises(ValueError, match="organization slug"):
        _normalize_inputs(_command(slug="Client Name"))


def test_clean_bootstrap_creates_requested_organization_without_reference_tenant() -> None:
    session = _OrganizationSession()

    organization, created = _get_or_create_organization(
        session,  # type: ignore[arg-type]
        name="Example Organization",
        slug="example-organization",
    )

    assert created is True
    assert organization.slug == "example-organization"
    assert organization.name == "Example Organization"
    assert organization.config["installation_bootstrap"] is True
    assert "reference" not in organization.slug


def test_same_organization_is_reused_idempotently() -> None:
    existing = Organization(
        id=uuid.uuid4(),
        slug="example-organization",
        name="Example Organization",
        status="active",
        config={"installation_bootstrap": True},
    )
    session = _OrganizationSession(existing)

    organization, created = _get_or_create_organization(
        session,  # type: ignore[arg-type]
        name="Example Organization",
        slug="example-organization",
    )

    assert organization is existing
    assert created is False
    assert session.added == []


def test_incompatible_slug_name_collision_fails_closed() -> None:
    existing = Organization(
        id=uuid.uuid4(),
        slug="example-organization",
        name="Different Organization",
        status="active",
        config={},
    )
    session = _OrganizationSession(existing)

    with pytest.raises(ValueError, match="different name"):
        _get_or_create_organization(
            session,  # type: ignore[arg-type]
            name="Example Organization",
            slug="example-organization",
        )


def test_installation_admin_catalog_contains_organization_administer_permission() -> None:
    permissions = {(resource, action) for resource, action, _description in INSTALLATION_ADMIN_PERMISSION_CATALOG}
    assert ("organization.security", "administer") in permissions
    assert ("documents", "administer") in permissions
    assert ("platform.assistants", "administer") in permissions


def test_platform_owner_catalog_contains_explicit_global_administration_permissions() -> None:
    permissions = {(resource, action) for resource, action, _description in PLATFORM_ADMIN_PERMISSION_CATALOG}

    assert PLATFORM_OWNER_ROLE_CODE == "platform-owner"
    assert {
        ("platform.organization_lifecycle", "administer"),
        ("platform.security", "administer"),
        ("platform.operations", "administer"),
        ("platform.production_acceptance", "administer"),
        ("platform.release_governance", "administer"),
        ("platform.configuration_preflight", "administer"),
        ("platform.recovery", "administer"),
        ("platform.observability", "administer"),
        ("platform.capacity", "administer"),
        ("platform.portal_acceptance", "administer"),
    }.issubset(permissions)
    assert all(resource != "*" and action != "*" for resource, action in permissions)


def test_platform_owner_authority_reconciliation_is_idempotent() -> None:
    session = _PlatformAuthoritySession()
    user_id = uuid.uuid4()

    first_role = reconcile_platform_owner_role(session, actor="installation-setup")  # type: ignore[arg-type]
    first_assignment = reconcile_platform_owner_assignment(
        session,  # type: ignore[arg-type]
        role=first_role,
        user_id=user_id,
        actor="installation-setup",
    )
    second_role = reconcile_platform_owner_role(session, actor="installation-setup")  # type: ignore[arg-type]
    second_assignment = reconcile_platform_owner_assignment(
        session,  # type: ignore[arg-type]
        role=second_role,
        user_id=user_id,
        actor="installation-setup",
    )

    assert second_role is first_role
    assert second_assignment is first_assignment
    assert len(session.roles) == 1
    assert len(session.permissions) == len(PLATFORM_ADMIN_PERMISSION_CATALOG)
    assert len(session.role_permissions) == len(PLATFORM_ADMIN_PERMISSION_CATALOG)
    assert len(session.assignments) == 1
    assert first_role.organization_id is None
    assert first_role.code == "platform-owner"
    assert first_role.config["scope"] == "platform"
    assert first_role.status == "active"
    assert first_role.is_system is False
    assert first_assignment.organization_id is None
    assert first_assignment.principal_type == "user"
    assert first_assignment.principal_id == str(user_id)
    assert first_assignment.scope_type == "platform"
    assert first_assignment.scope_id == "platform"
    assert first_assignment.status == "active"


def test_installation_bootstrap_reuses_existing_identity_bootstrap() -> None:
    bootstrap_source = Path("apps/api/app/identity/installation_bootstrap.py").read_text(encoding="utf-8")
    setup_source = Path("apps/api/app/services/installation_setup.py").read_text(encoding="utf-8")

    assert "InstallationSetupService(" in bootstrap_source
    assert "bootstrap_initial_admin(" in setup_source
    identity_source = Path("apps/api/app/identity/bootstrap.py").read_text(encoding="utf-8")
    cli_source = Path("apps/api/app/cli/__main__.py").read_text(encoding="utf-8")

    assert "PasswordContext(" in identity_source
    assert "validate_password(command.password, context=password_context)" in identity_source
    assert "bootstrap_initial_admin(" in cli_source
    assert "PasswordCredential(" not in setup_source
    assert "OrganizationMembership(" not in setup_source
    assert "RoleAssignment(" not in setup_source
    assert "reference_tenant" not in bootstrap_source


def test_first_run_reconciles_independent_organization_and_platform_grants() -> None:
    setup_source = Path("apps/api/app/services/installation_setup.py").read_text(encoding="utf-8")
    platform_source = Path("apps/api/app/security/platform_roles.py").read_text(encoding="utf-8")
    reference_source = Path("apps/api/app/services/reference_tenant.py").read_text(encoding="utf-8")

    assert "reconcile_platform_owner_role(self.platform_db" in setup_source
    assert "reconcile_platform_owner_assignment(" in setup_source
    assert '"platform_role_id": str(platform_role.id)' in setup_source
    assert '"platform_assignment_id": str(platform_assignment.id)' in setup_source
    assert "organization_id=None" in platform_source
    assert 'principal_type="user"' in platform_source
    assert 'scope_type="platform"' in platform_source
    assert 'scope_id="platform"' in platform_source
    assert "REFERENCE_PLATFORM_PERMISSIONS = PLATFORM_ADMIN_PERMISSION_CATALOG" in reference_source
    assert "reference-platform-operator" not in setup_source


def test_completed_platform_owner_reconciliation_is_an_explicit_cli_operation() -> None:
    args = build_parser().parse_args(["reconcile-installation-platform-owner"])

    assert args.command == "reconcile-installation-platform-owner"
