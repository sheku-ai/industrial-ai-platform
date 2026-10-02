from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission

PERMISSIONS = (
    ("control_plane.health", "read"),
    ("control_plane.reconciliation", "read"),
    ("control_plane.reconciliation", "administer"),
    ("control_plane.workers", "read"),
    ("control_plane.workers", "administer"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization", required=True, help="Organization UUID or slug")
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--principal-type", default="user")
    parser.add_argument("--role-code", required=True)
    parser.add_argument("--role-name", default="Control Plane Operator")
    return parser.parse_args()


def resolve_organization(session, value: str) -> Organization:
    try:
        organization_id = UUID(value)
    except ValueError:
        organization_id = None
    organization = session.scalar(
        select(Organization).where(
            or_(
                Organization.id == organization_id if organization_id else False,
                Organization.slug == value,
            )
        )
    )
    if organization is None:
        raise RuntimeError(f"organization not found: {value}")
    return organization


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    args = parse_args()
    now = datetime.now(UTC)
    with SessionLocal() as session:
        organization = resolve_organization(session, args.organization)
        role = session.scalar(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.code == args.role_code,
            )
        )
        if role is None:
            role = Role(
                organization_id=organization.id,
                code=args.role_code,
                name=args.role_name,
                description="Configurable role for authorized control-plane operations",
                is_system=False,
                status="active",
                config={},
                created_at=now,
                updated_at=now,
            )
            session.add(role)
            session.flush()

        for resource, action in PERMISSIONS:
            permission = session.scalar(
                select(Permission).where(
                    Permission.resource == resource,
                    Permission.action == action,
                )
            )
            if permission is None:
                permission = Permission(
                    resource=resource,
                    action=action,
                    description=f"Allows {action} on {resource}",
                    created_at=now,
                    updated_at=now,
                )
                session.add(permission)
                session.flush()

            linked = session.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if linked is None:
                session.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                        created_at=now,
                        updated_at=now,
                    )
                )

        assignment = session.scalar(
            select(RoleAssignment).where(
                RoleAssignment.organization_id == organization.id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.principal_type == args.principal_type,
                RoleAssignment.principal_id == args.principal_id,
                RoleAssignment.status == "active",
            )
        )
        if assignment is None:
            session.add(
                RoleAssignment(
                    organization_id=organization.id,
                    role_id=role.id,
                    principal_type=args.principal_type,
                    principal_id=args.principal_id,
                    scope_type="organization",
                    scope_id=str(organization.id),
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )

        session.commit()
        print(
            json.dumps(
                {
                    "organization_id": str(organization.id),
                    "organization_slug": organization.slug,
                    "principal_id": args.principal_id,
                    "principal_type": args.principal_type,
                    "role_code": role.code,
                    "permissions": [f"{resource}:{action}" for resource, action in PERMISSIONS],
                    "passed": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
