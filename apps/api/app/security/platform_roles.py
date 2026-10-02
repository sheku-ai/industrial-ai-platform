from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import Permission, Role, RoleAssignment, RolePermission

PLATFORM_ADMIN_PERMISSION_CATALOG = (
    ("platform.organization_lifecycle", "read", "Read governed organization deletion evidence."),
    ("platform.organization_lifecycle", "administer", "Administer governed organization deletion."),
    ("control_plane.workers", "read", "Read platform worker state."),
    ("control_plane.workers", "administer", "Administer platform worker desired state."),
    ("platform.production_acceptance", "read", "Read Production Acceptance evidence and readiness."),
    ("platform.production_acceptance", "administer", "Run Production Acceptance evaluations."),
    ("platform.capacity", "read", "Read governed Capacity and Load evidence and readiness."),
    ("platform.capacity", "administer", "Administer Capacity profiles, load evidence, and evaluations."),
    ("platform.portal_acceptance", "read", "Read governed Portal Acceptance evidence."),
    ("platform.portal_acceptance", "administer", "Register governed Portal Acceptance evidence."),
    ("platform.observability", "read", "Read persisted observability evidence and health readiness."),
    ("platform.observability", "administer", "Administer observability profiles and persisted health evidence."),
    ("platform.release_governance", "read", "Read governed releases, artifacts, manifests, and readiness."),
    ("platform.release_governance", "administer", "Administer governed release evidence and acceptance."),
    ("platform.configuration_preflight", "read", "Read safe platform configuration preflight."),
    (
        "platform.configuration_preflight",
        "administer",
        "Execute and persist governed platform configuration preflight evidence.",
    ),
    ("platform.recovery", "read", "Read recovery policy, execution, verification, and readiness evidence."),
    ("platform.recovery", "administer", "Administer recovery policies and register external recovery evidence."),
    ("platform.operations", "read", "Read operational observability, incidents, retries, leases, and readiness."),
    ("platform.operations", "administer", "Administer operational evidence, incidents, and recovery actions."),
    ("platform.security", "read", "Read security readiness, findings, evidence, policies, and configuration."),
    ("platform.security", "administer", "Administer security policies and trigger security evaluation."),
)

PLATFORM_OWNER_ROLE_CODE = "platform-owner"
PLATFORM_OWNER_ROLE_NAME = "Platform Owner"
PLATFORM_OWNER_ROLE_DESCRIPTION = "Initial delegable administrator of the platform instance."


def platform_role_criteria():
    return (
        Role.organization_id.is_(None),
        Role.config["scope"].as_string() == "platform",
    )


def is_platform_role(role: Role | None, *, require_active: bool = False) -> bool:
    if role is None or role.organization_id is not None:
        return False
    config = role.config if isinstance(role.config, dict) else {}
    return config.get("scope") == "platform" and (not require_active or role.status == "active")


def reconcile_platform_owner_role(db: Session, *, actor: str) -> Role:
    role = db.scalar(
        select(Role).where(
            Role.organization_id.is_(None),
            Role.code == PLATFORM_OWNER_ROLE_CODE,
        )
    )
    if role is None:
        role = Role(
            organization_id=None,
            code=PLATFORM_OWNER_ROLE_CODE,
            name=PLATFORM_OWNER_ROLE_NAME,
            description=PLATFORM_OWNER_ROLE_DESCRIPTION,
            is_system=False,
            status="active",
            config={"scope": "platform", "installation_bootstrap": True},
            created_by=actor,
            updated_by=actor,
        )
        db.add(role)
        db.flush()
    else:
        role.name = PLATFORM_OWNER_ROLE_NAME
        role.description = PLATFORM_OWNER_ROLE_DESCRIPTION
        role.is_system = False
        role.status = "active"
        role.config = {**(role.config or {}), "scope": "platform", "installation_bootstrap": True}
        role.updated_by = actor
        db.add(role)
        db.flush()

    for resource, action, description in PLATFORM_ADMIN_PERMISSION_CATALOG:
        permission = db.scalar(
            select(Permission).where(
                Permission.resource == resource,
                Permission.action == action,
            )
        )
        if permission is None:
            permission = Permission(
                resource=resource,
                action=action,
                description=description,
                created_by=actor,
                updated_by=actor,
            )
            db.add(permission)
            db.flush()
        link = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == permission.id,
            )
        )
        if link is None:
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
            db.flush()
    return role


def reconcile_platform_owner_assignment(
    db: Session,
    *,
    role: Role,
    user_id: UUID,
    actor: str,
) -> RoleAssignment:
    assignment = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.organization_id.is_(None),
            RoleAssignment.role_id == role.id,
            RoleAssignment.principal_type == "user",
            RoleAssignment.principal_id == str(user_id),
            RoleAssignment.scope_type == "platform",
            RoleAssignment.scope_id == "platform",
        )
    )
    if assignment is None:
        assignment = RoleAssignment(
            organization_id=None,
            role_id=role.id,
            principal_type="user",
            principal_id=str(user_id),
            scope_type="platform",
            scope_id="platform",
            status="active",
            created_by=actor,
            updated_by=actor,
        )
        db.add(assignment)
        db.flush()
    elif assignment.status != "active":
        assignment.status = "active"
        assignment.updated_by = actor
        db.add(assignment)
        db.flush()
    return assignment
