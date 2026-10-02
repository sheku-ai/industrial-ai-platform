from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, delete, select, text
from sqlalchemy.orm import Session

from app.identity.models import IdentityUser, OrganizationMembership, PasswordCredential
from app.identity.service import available_username_from_email, normalize_email
from app.models.audit import AuditEvent, AuditHistory
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.schemas.organization_access import (
    OrganizationMembershipUpdate,
    OrganizationPolicyCreate,
    OrganizationPolicyUpdate,
    OrganizationRoleAssignmentCreate,
    OrganizationRoleCreate,
    OrganizationRoleDuplicate,
    OrganizationRoleUpdate,
    OrganizationUserCreate,
)

ADMIN_PERMISSION = "organization.security:administer"
NON_DELEGABLE_RESOURCE_PREFIXES = ("control_plane.",)
NON_DELEGABLE_RESOURCES = {
    "platform.capacity",
    "platform.observability",
    "platform.operations",
    "platform.portal_acceptance",
    "platform.production_acceptance",
    "platform.recovery",
    "platform.release_governance",
    "platform.security",
    "product_acceptance",
}
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class OrganizationAccessError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_key(*values: object) -> int:
    digest = hashlib.sha256("|".join(str(value) for value in values).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _safe_state(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): (
            item.isoformat()
            if isinstance(item, datetime)
            else str(item)
            if isinstance(item, uuid.UUID)
            else item
        )
        for key, item in value.items()
    }


class OrganizationAccessManagementService:
    def __init__(
        self,
        db: Session,
        identity_db: Session,
        *,
        organization_id: uuid.UUID,
        actor_reference: str,
        actor_permissions: frozenset[str],
        correlation_id: str | None,
    ) -> None:
        self.db = db
        self.identity_db = identity_db
        self.organization_id = organization_id
        self.actor_reference = actor_reference
        self.actor_permissions = actor_permissions
        self.correlation_id = correlation_id

    def runtime(self) -> dict[str, Any]:
        memberships = self._memberships(include_removed=True)
        user_ids = {membership.user_id for membership in memberships}
        users = {
            user.id: user
            for user in self.identity_db.scalars(
                select(IdentityUser).where(IdentityUser.id.in_(user_ids))
            ).all()
        } if user_ids else {}
        credentials = set(
            self.identity_db.scalars(
                select(PasswordCredential.user_id).where(PasswordCredential.user_id.in_(user_ids))
            ).all()
        ) if user_ids else set()

        roles = list(
            self.db.scalars(
                select(Role)
                .where(Role.organization_id == self.organization_id)
                .order_by(Role.name, Role.code)
            ).all()
        )
        role_ids = {role.id for role in roles}
        catalog_permissions = list(
            self.db.scalars(select(Permission).order_by(Permission.resource, Permission.action)).all()
        )
        permissions_by_key: dict[str, Permission] = {}
        duplicate_permission_keys: set[str] = set()
        for permission in catalog_permissions:
            key = self._permission_key(permission)
            current = permissions_by_key.get(key)
            if current is not None:
                duplicate_permission_keys.add(key)
            if current is None or (
                self._permission_is_canonical(permission)
                and not self._permission_is_canonical(current)
            ):
                permissions_by_key[key] = permission
        permissions = list(permissions_by_key.values())
        permission_by_id = {permission.id: permission for permission in catalog_permissions}
        role_permissions = list(
            self.db.scalars(
                select(RolePermission).where(RolePermission.role_id.in_(role_ids))
            ).all()
        ) if role_ids else []
        permission_ids_by_role: dict[uuid.UUID, list[uuid.UUID]] = {}
        for link in role_permissions:
            linked_permission = permission_by_id.get(link.permission_id)
            if linked_permission is None:
                continue
            representative = permissions_by_key[self._permission_key(linked_permission)]
            role_permission_ids = permission_ids_by_role.setdefault(link.role_id, [])
            if representative.id not in role_permission_ids:
                role_permission_ids.append(representative.id)

        assignments = list(
            self.db.scalars(
                select(RoleAssignment)
                .where(RoleAssignment.organization_id == self.organization_id)
                .order_by(RoleAssignment.created_at, RoleAssignment.id)
            ).all()
        )
        assignments_by_principal: dict[str, list[RoleAssignment]] = {}
        for assignment in assignments:
            assignments_by_principal.setdefault(assignment.principal_id, []).append(assignment)
        users_by_principal = {str(user_id): user for user_id, user in users.items()}
        memberships_by_principal = {
            str(membership.user_id): membership
            for membership in memberships
        }

        user_rows: list[dict[str, Any]] = []
        for membership in memberships:
            user = users.get(membership.user_id)
            if user is None:
                continue
            user_rows.append(
                {
                    "membership_id": membership.id,
                    "user_id": user.id,
                    "organization_id": membership.organization_id,
                    "email": user.email_display,
                    "display_name": user.display_name,
                    "identity_type": "password" if user.id in credentials else "unprovisioned",
                    "identity_status": user.status,
                    "membership_status": membership.status,
                    "primary_role_id": membership.role_id,
                    "roles": [
                        {
                            "assignment_id": assignment.id,
                            "role_id": assignment.role_id,
                            "status": assignment.status,
                        }
                        for assignment in assignments_by_principal.get(str(user.id), [])
                    ],
                    "created_at": membership.created_at,
                    "updated_at": membership.updated_at,
                }
            )

        role_rows = [
            {
                "id": role.id,
                "code": role.code,
                "name": role.name,
                "description": role.description,
                "status": role.status,
                "is_system": role.is_system,
                "protected": self._role_is_protected(role),
                "permission_ids": permission_ids_by_role.get(role.id, []),
                "created_at": role.created_at,
                "updated_at": role.updated_at,
            }
            for role in roles
        ]
        permission_rows = []
        non_delegable_permission_rows = []
        for permission in permissions:
            row = {
                "id": permission.id,
                "resource": self._permission_resource(permission),
                "action": self._permission_action(permission),
                "description": permission.description,
                "key": self._permission_key(permission),
                "delegable": self._permission_is_delegable(permission),
            }
            if row["delegable"]:
                permission_rows.append(row)
            else:
                non_delegable_permission_rows.append(row)
        human_assignments = [
            assignment
            for assignment in assignments
            if (
                assignment.principal_type == "user"
                and assignment.principal_id in users_by_principal
                and assignment.principal_id in memberships_by_principal
            )
        ]
        technical_assignments = [
            assignment
            for assignment in assignments
            if assignment not in human_assignments
        ]
        policies = list(
            self.db.scalars(
                select(Policy)
                .where(Policy.organization_id == self.organization_id)
                .order_by(Policy.name, Policy.code)
            ).all()
        )
        return {
            "runtime_name": "organization_access_management",
            "runtime_status": "ready",
            "organization_id": self.organization_id,
            "users": user_rows,
            "roles": role_rows,
            "permissions": permission_rows,
            "non_delegable_permissions": non_delegable_permission_rows,
            "policies": [
                {
                    "id": policy.id,
                    "code": policy.code,
                    "name": policy.name,
                    "effect": policy.effect,
                    "rules": policy.rules or {},
                    "status": policy.status,
                    "created_at": policy.created_at,
                    "updated_at": policy.updated_at,
                }
                for policy in policies
            ],
            "assignments": [
                {
                    "id": assignment.id,
                    "role_id": assignment.role_id,
                    "principal_type": assignment.principal_type,
                    "principal_id": assignment.principal_id,
                    "scope_type": assignment.scope_type,
                    "scope_id": assignment.scope_id,
                    "status": assignment.status,
                    "created_at": assignment.created_at,
                    "updated_at": assignment.updated_at,
                    "membership_id": memberships_by_principal[assignment.principal_id].id,
                    "display_name": users_by_principal[assignment.principal_id].display_name,
                    "email": users_by_principal[assignment.principal_id].email_display,
                    "identity_type": (
                        "password"
                        if users_by_principal[assignment.principal_id].id in credentials
                        else "unprovisioned"
                    ),
                    "identity_status": users_by_principal[assignment.principal_id].status,
                    "membership_status": memberships_by_principal[assignment.principal_id].status,
                }
                for assignment in human_assignments
            ],
            "technical_principals": [
                {
                    "assignment_id": assignment.id,
                    "role_id": assignment.role_id,
                    "role_name": next(
                        (role.name for role in roles if role.id == assignment.role_id),
                        str(assignment.role_id),
                    ),
                    "principal_type": assignment.principal_type,
                    "principal_id": assignment.principal_id,
                    "scope_type": assignment.scope_type,
                    "scope_id": assignment.scope_id,
                    "status": assignment.status,
                    "created_at": assignment.created_at,
                    "updated_at": assignment.updated_at,
                }
                for assignment in technical_assignments
            ],
            "capabilities": {
                "read": "organization.security:read" in self.actor_permissions
                or ADMIN_PERMISSION in self.actor_permissions,
                "administer": ADMIN_PERMISSION in self.actor_permissions,
                "email_delivery": False,
            },
            "diagnostics": {
                "identity_source_of_truth": "identity_postgresql",
                "authorization_source_of_truth": "platform_postgresql",
                "email_delivery": "not_configured",
                "normalized_duplicate_permission_keys": sorted(duplicate_permission_keys),
            },
            "postgresql_source_of_truth": True,
        }

    def create_user(self, payload: OrganizationUserCreate) -> dict[str, Any]:
        role = self._role(payload.role_id, active=True)
        self._assert_role_delegable(role)
        try:
            normalized_email = normalize_email(payload.email)
        except ValueError as exc:
            raise OrganizationAccessError(422, "invalid_email") from exc
        self.identity_db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _lock_key("organization_identity", normalized_email)},
        )

        user = self.identity_db.scalar(
            select(IdentityUser).where(IdentityUser.email_normalized == normalized_email)
        )
        if user is None:
            user = IdentityUser(
                username=available_username_from_email(self.identity_db, payload.email),
                email_normalized=normalized_email,
                email_display=payload.email.strip(),
                display_name=(payload.display_name or "").strip() or None,
                status="active",
                must_change_password=False,
            )
            self.identity_db.add(user)
            self.identity_db.flush()
        elif user.status != "active":
            raise OrganizationAccessError(409, "identity_not_active")

        memberships = list(
            self.identity_db.scalars(
                select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == self.organization_id,
                ).order_by(
                    case(
                        (OrganizationMembership.status == "active", 0),
                        (OrganizationMembership.role_id == role.id, 1),
                        else_=2,
                    ),
                    OrganizationMembership.created_at.desc(),
                )
            ).all()
        )
        membership = memberships[0] if memberships else None
        before: dict[str, Any] = {}
        if membership is None:
            membership = OrganizationMembership(
                user_id=user.id,
                organization_id=self.organization_id,
                role_id=role.id,
                status="active",
            )
            self.identity_db.add(membership)
        elif membership.status == "active":
            if membership.role_id != role.id:
                raise OrganizationAccessError(409, "organization_membership_exists")
            assignment, changed = self._upsert_assignment(user.id, role.id)
            if changed:
                self._audit(
                    resource_type="security_role_assignment",
                    resource_id=assignment.id,
                    action="role_assignment.reconciled",
                    after={"role_id": role.id, "principal_id": user.id},
                )
                self.db.commit()
            return {
                "membership_id": membership.id,
                "user_id": user.id,
                "email_delivery": "not_configured",
                "idempotent": not changed,
            }
        else:
            before = {"membership_status": membership.status, "primary_role_id": membership.role_id}
            membership.role_id = role.id
            membership.status = "active"
            membership.suspended_at = None
            membership.removed_at = None
        self.identity_db.commit()
        self.identity_db.refresh(membership)

        assignment, _ = self._upsert_assignment(user.id, role.id)
        self._audit(
            resource_type="organization_membership",
            resource_id=membership.id,
            action="membership.created" if not before else "membership.reactivated",
            before=before,
            after={
                "user_id": user.id,
                "membership_status": membership.status,
                "primary_role_id": role.id,
                "assignment_id": assignment.id,
                "email_delivery": "not_configured",
            },
        )
        self.db.commit()
        return {"membership_id": membership.id, "user_id": user.id, "email_delivery": "not_configured"}

    def update_membership(
        self,
        membership_id: uuid.UUID,
        payload: OrganizationMembershipUpdate,
    ) -> dict[str, Any]:
        membership = self._membership(membership_id)
        user = self._identity_user(membership.user_id)
        other_membership = self.identity_db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id != self.organization_id,
                OrganizationMembership.status != "removed",
            )
        )
        if other_membership is not None:
            raise OrganizationAccessError(409, "shared_identity_profile_not_organization_editable")
        before = {"display_name": user.display_name}
        user.display_name = payload.display_name.strip()
        self.identity_db.commit()
        self._audit(
            resource_type="identity_profile",
            resource_id=user.id,
            action="identity_profile.updated",
            before=before,
            after={"display_name": user.display_name},
        )
        self.db.commit()
        return {"membership_id": membership.id, "user_id": user.id}

    def set_membership_status(self, membership_id: uuid.UUID, status: str) -> dict[str, Any]:
        membership = self._membership(membership_id)
        if status not in {"active", "suspended", "removed"}:
            raise OrganizationAccessError(422, "invalid_membership_status")
        if membership.status == status:
            return {"membership_id": membership.id, "status": status, "idempotent": True}
        if status != "active":
            self._ensure_admin_remaining(exclude_principal_id=str(membership.user_id))
        before = {"membership_status": membership.status}
        membership.status = status
        membership.suspended_at = _now() if status == "suspended" else None
        membership.removed_at = _now() if status == "removed" else None
        self.identity_db.commit()
        self._audit(
            resource_type="organization_membership",
            resource_id=membership.id,
            action=f"membership.{status}",
            before=before,
            after={"membership_status": status, "user_id": membership.user_id},
        )
        self.db.commit()
        return {"membership_id": membership.id, "status": status}

    def create_role(self, payload: OrganizationRoleCreate) -> dict[str, Any]:
        code = self._validate_code(payload.code)
        role = Role(
            organization_id=self.organization_id,
            code=code,
            name=payload.name.strip(),
            description=payload.description,
            is_system=False,
            status="active",
            config={"organization_managed": True},
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.db.add(role)
        self.db.flush()
        self._audit(
            resource_type="security_role",
            resource_id=role.id,
            action="role.created",
            after=self._role_state(role),
        )
        self.db.commit()
        return {"id": role.id}

    def update_role(self, role_id: uuid.UUID, payload: OrganizationRoleUpdate) -> dict[str, Any]:
        role = self._role(role_id)
        self._assert_role_mutable(role)
        before = self._role_state(role)
        if payload.name is not None:
            role.name = payload.name.strip()
        if "description" in payload.model_fields_set:
            role.description = payload.description
        role.updated_by = self.actor_reference
        self._audit(
            resource_type="security_role",
            resource_id=role.id,
            action="role.updated",
            before=before,
            after=self._role_state(role),
        )
        self.db.commit()
        return {"id": role.id}

    def duplicate_role(self, role_id: uuid.UUID, payload: OrganizationRoleDuplicate) -> dict[str, Any]:
        source = self._role(role_id)
        duplicate = Role(
            organization_id=self.organization_id,
            code=self._validate_code(payload.code),
            name=payload.name.strip(),
            description=source.description,
            is_system=False,
            status="active",
            config={"organization_managed": True, "duplicated_from": str(source.id)},
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.db.add(duplicate)
        self.db.flush()
        for permission_id in self.db.scalars(
            select(RolePermission.permission_id).where(RolePermission.role_id == source.id)
        ).all():
            permission = self._permission(permission_id)
            self._assert_permission_delegable(permission)
            self.db.add(
                RolePermission(
                    role_id=duplicate.id,
                    permission_id=permission.id,
                    created_by=self.actor_reference,
                    updated_by=self.actor_reference,
                )
            )
        self._audit(
            resource_type="security_role",
            resource_id=duplicate.id,
            action="role.duplicated",
            after={**self._role_state(duplicate), "source_role_id": source.id},
        )
        self.db.commit()
        return {"id": duplicate.id}

    def archive_role(self, role_id: uuid.UUID) -> dict[str, Any]:
        return self.set_role_status(role_id, "archived")

    def set_role_status(self, role_id: uuid.UUID, status: str) -> dict[str, Any]:
        role = self._role(role_id)
        self._assert_role_mutable(role)
        if status not in {"active", "inactive", "archived"}:
            raise OrganizationAccessError(422, "invalid_role_status")
        if role.status == status:
            return {"id": role.id, "status": role.status, "idempotent": True}
        before = self._role_state(role)
        role.status = status
        role.updated_by = self.actor_reference
        self.db.flush()
        self._ensure_admin_remaining()
        self._audit(
            resource_type="security_role",
            resource_id=role.id,
            action=f"role.{status}",
            before=before,
            after=self._role_state(role),
        )
        self.db.commit()
        return {"id": role.id, "status": role.status}

    def delete_role(self, role_id: uuid.UUID) -> dict[str, Any]:
        role = self._role(role_id)
        self._assert_role_mutable(role)
        assigned = self.db.scalar(
            select(RoleAssignment.id).where(
                RoleAssignment.organization_id == self.organization_id,
                RoleAssignment.role_id == role.id,
            )
        )
        if assigned is not None:
            raise OrganizationAccessError(409, "role_has_assignments")
        before = self._role_state(role)
        self.db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        self.db.delete(role)
        self.db.flush()
        self._ensure_admin_remaining()
        self._audit(
            resource_type="security_role",
            resource_id=role_id,
            action="role.deleted",
            before=before,
        )
        self.db.commit()
        return {"id": role_id, "deleted": True}

    def add_role_permission(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> dict[str, Any]:
        role = self._role(role_id)
        self._assert_role_mutable(role)
        permission = self._permission(permission_id)
        self._assert_permission_delegable(permission)
        existing_links = self._role_permission_links_for_key(role.id, self._permission_key(permission))
        if existing_links:
            return {"id": existing_links[0].id, "idempotent": True}
        link = RolePermission(
            role_id=role.id,
            permission_id=permission.id,
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.db.add(link)
        self.db.flush()
        self._audit(
            resource_type="security_role_permission",
            resource_id=link.id,
            action="role_permission.attached",
            after={"role_id": role.id, "permission_id": permission.id, "permission": self._permission_key(permission)},
        )
        self.db.commit()
        return {"id": link.id}

    def remove_role_permission(self, role_id: uuid.UUID, permission_id: uuid.UUID) -> dict[str, Any]:
        role = self._role(role_id)
        self._assert_role_mutable(role)
        permission = self._permission(permission_id)
        self._assert_permission_delegable(permission)
        links = self._role_permission_links_for_key(role.id, self._permission_key(permission))
        if not links:
            return {"removed": False, "idempotent": True}
        link_ids = [link.id for link in links]
        for link in links:
            self.db.delete(link)
        self.db.flush()
        self._ensure_admin_remaining()
        self._audit(
            resource_type="security_role_permission",
            resource_id=link_ids[0],
            action="role_permission.detached",
            before={
                "role_id": role.id,
                "permission_id": permission.id,
                "permission": self._permission_key(permission),
                "normalized_link_ids": [str(link_id) for link_id in link_ids],
            },
        )
        self.db.commit()
        return {"removed": True, "removed_links": len(link_ids)}

    def create_assignment(self, payload: OrganizationRoleAssignmentCreate) -> dict[str, Any]:
        membership = self._membership(payload.membership_id, active=True)
        role = self._role(payload.role_id, active=True)
        self._assert_role_delegable(role)
        assignment, changed = self._upsert_assignment(membership.user_id, role.id)
        if changed:
            self._audit(
                resource_type="security_role_assignment",
                resource_id=assignment.id,
                action="role_assignment.assigned",
                after={"role_id": role.id, "principal_id": membership.user_id},
            )
            self.db.commit()
        return {"id": assignment.id, "idempotent": not changed}

    def remove_assignment(self, assignment_id: uuid.UUID) -> dict[str, Any]:
        assignment = self._assignment(assignment_id)
        if assignment.principal_type != "user":
            raise OrganizationAccessError(409, "technical_assignment_not_organization_managed")
        try:
            principal_user_id = uuid.UUID(assignment.principal_id)
        except ValueError as exc:
            raise OrganizationAccessError(409, "technical_assignment_not_organization_managed") from exc
        membership = self.identity_db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.user_id == principal_user_id,
                OrganizationMembership.organization_id == self.organization_id,
            )
        )
        if membership is None:
            raise OrganizationAccessError(409, "technical_assignment_not_organization_managed")
        if assignment.status != "active":
            return {"id": assignment.id, "status": assignment.status, "idempotent": True}
        before = self._assignment_state(assignment)
        assignment.status = "removed"
        assignment.updated_by = self.actor_reference
        self.db.flush()
        self._ensure_admin_remaining()
        self._audit(
            resource_type="security_role_assignment",
            resource_id=assignment.id,
            action="role_assignment.removed",
            before=before,
            after=self._assignment_state(assignment),
        )
        self.db.commit()
        return {"id": assignment.id, "status": assignment.status}

    def create_policy(self, payload: OrganizationPolicyCreate) -> dict[str, Any]:
        self._validate_policy_rules(payload.rules)
        policy = Policy(
            organization_id=self.organization_id,
            code=self._validate_code(payload.code),
            name=payload.name.strip(),
            effect=payload.effect,
            rules=payload.rules,
            status="active",
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.db.add(policy)
        self.db.flush()
        self._audit(
            resource_type="security_policy",
            resource_id=policy.id,
            action="policy.created",
            after=self._policy_state(policy),
        )
        self.db.commit()
        return {"id": policy.id}

    def update_policy(self, policy_id: uuid.UUID, payload: OrganizationPolicyUpdate) -> dict[str, Any]:
        policy = self._policy(policy_id)
        before = self._policy_state(policy)
        candidate_rules = payload.rules if payload.rules is not None else policy.rules
        self._validate_policy_rules(candidate_rules or {})
        if payload.name is not None:
            policy.name = payload.name.strip()
        if payload.effect is not None:
            policy.effect = payload.effect
        if payload.rules is not None:
            self._validate_policy_rules(payload.rules)
            policy.rules = payload.rules
        policy.updated_by = self.actor_reference
        self._audit(
            resource_type="security_policy",
            resource_id=policy.id,
            action="policy.updated",
            before=before,
            after=self._policy_state(policy),
        )
        self.db.commit()
        return {"id": policy.id}

    def set_policy_status(self, policy_id: uuid.UUID, status: str) -> dict[str, Any]:
        policy = self._policy(policy_id)
        if status not in {"active", "inactive", "archived"}:
            raise OrganizationAccessError(422, "invalid_policy_status")
        if policy.status == status:
            return {"id": policy.id, "status": status, "idempotent": True}
        if status == "active":
            self._validate_policy_rules(policy.rules or {})
        before = self._policy_state(policy)
        policy.status = status
        policy.updated_by = self.actor_reference
        self.db.flush()
        self._ensure_admin_remaining()
        self._audit(
            resource_type="security_policy",
            resource_id=policy.id,
            action=f"policy.{status}",
            before=before,
            after=self._policy_state(policy),
        )
        self.db.commit()
        return {"id": policy.id, "status": status}

    def _memberships(self, *, include_removed: bool) -> list[OrganizationMembership]:
        statement = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == self.organization_id
        )
        if not include_removed:
            statement = statement.where(OrganizationMembership.status != "removed")
        return list(self.identity_db.scalars(statement.order_by(OrganizationMembership.created_at)).all())

    def _membership(
        self,
        membership_id: uuid.UUID,
        *,
        active: bool = False,
    ) -> OrganizationMembership:
        membership = self.identity_db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.id == membership_id,
                OrganizationMembership.organization_id == self.organization_id,
            )
        )
        if membership is None:
            raise OrganizationAccessError(404, "organization_membership_not_found")
        if active and membership.status != "active":
            raise OrganizationAccessError(409, "organization_membership_not_active")
        return membership

    def _identity_user(self, user_id: uuid.UUID) -> IdentityUser:
        user = self.identity_db.get(IdentityUser, user_id)
        if user is None:
            raise OrganizationAccessError(404, "identity_not_found")
        return user

    def _role(self, role_id: uuid.UUID, *, active: bool = False) -> Role:
        role = self.db.scalar(
            select(Role).where(
                Role.id == role_id,
                Role.organization_id == self.organization_id,
            )
        )
        if role is None:
            raise OrganizationAccessError(404, "organization_role_not_found")
        if active and role.status != "active":
            raise OrganizationAccessError(409, "organization_role_not_active")
        return role

    def _permission(self, permission_id: uuid.UUID) -> Permission:
        permission = self.db.get(Permission, permission_id)
        if permission is None:
            raise OrganizationAccessError(404, "permission_not_found")
        return permission

    def _role_permission_links_for_key(
        self,
        role_id: uuid.UUID,
        permission_key: str,
    ) -> list[RolePermission]:
        rows = self.db.execute(
            select(RolePermission, Permission)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id == role_id)
            .order_by(RolePermission.created_at, RolePermission.id)
        ).all()
        return [
            link
            for link, linked_permission in rows
            if self._permission_key(linked_permission) == permission_key
        ]

    def _policy(self, policy_id: uuid.UUID) -> Policy:
        policy = self.db.scalar(
            select(Policy).where(
                Policy.id == policy_id,
                Policy.organization_id == self.organization_id,
            )
        )
        if policy is None:
            raise OrganizationAccessError(404, "organization_policy_not_found")
        return policy

    def _assignment(self, assignment_id: uuid.UUID) -> RoleAssignment:
        assignment = self.db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.id == assignment_id,
                RoleAssignment.organization_id == self.organization_id,
            )
        )
        if assignment is None:
            raise OrganizationAccessError(404, "organization_assignment_not_found")
        return assignment

    def _upsert_assignment(self, user_id: uuid.UUID, role_id: uuid.UUID) -> tuple[RoleAssignment, bool]:
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {
                "lock_key": _lock_key(
                    "organization_role_assignment",
                    self.organization_id,
                    user_id,
                    role_id,
                )
            },
        )
        assignment = self.db.scalar(
            select(RoleAssignment)
            .where(
                RoleAssignment.organization_id == self.organization_id,
                RoleAssignment.role_id == role_id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id == str(user_id),
                RoleAssignment.scope_type == "organization",
                RoleAssignment.scope_id == str(self.organization_id),
            )
            .order_by(RoleAssignment.created_at)
        )
        if assignment is None:
            assignment = RoleAssignment(
                organization_id=self.organization_id,
                role_id=role_id,
                principal_type="user",
                principal_id=str(user_id),
                scope_type="organization",
                scope_id=str(self.organization_id),
                status="active",
                created_by=self.actor_reference,
                updated_by=self.actor_reference,
            )
            self.db.add(assignment)
            self.db.flush()
            return assignment, True
        elif assignment.status != "active":
            assignment.status = "active"
            assignment.updated_by = self.actor_reference
            self.db.flush()
            return assignment, True
        return assignment, False

    def _assert_role_mutable(self, role: Role) -> None:
        if self._role_is_protected(role):
            raise OrganizationAccessError(409, "protected_role")

    def _assert_role_delegable(self, role: Role) -> None:
        permission_ids = self.db.scalars(
            select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
        ).all()
        for permission_id in permission_ids:
            self._assert_permission_delegable(self._permission(permission_id))

    def _assert_permission_delegable(self, permission: Permission) -> None:
        if not self._permission_is_delegable(permission):
            raise OrganizationAccessError(403, "permission_not_delegable")

    def _permission_is_delegable(self, permission: Permission) -> bool:
        resource = self._permission_resource(permission)
        if resource.startswith("platform.") and resource != "platform.assistants":
            return False
        if resource in NON_DELEGABLE_RESOURCES:
            return False
        if resource.startswith(NON_DELEGABLE_RESOURCE_PREFIXES):
            return False
        return self._permission_key(permission) in self.actor_permissions

    def _role_is_protected(self, role: Role) -> bool:
        config = role.config if isinstance(role.config, dict) else {}
        return bool(
            role.is_system
            or config.get("protected")
            or config.get("baseline_required")
            or config.get("reference_tenant")
            or config.get("canonical_product_reference")
            or config.get("managed_by") == "platform"
        )

    def _validate_policy_rules(self, rules: dict[str, Any]) -> None:
        principals = rules.get("principals")
        if not isinstance(principals, dict):
            raise OrganizationAccessError(422, "policy_principals_required")
        principal_ids = principals.get("ids") or principals.get("principal_ids")
        if not isinstance(principal_ids, list) or not principal_ids:
            raise OrganizationAccessError(422, "policy_principal_ids_required")
        active_user_ids = {str(membership.user_id) for membership in self._memberships(include_removed=False)}
        if any(str(principal_id) not in active_user_ids for principal_id in principal_ids):
            raise OrganizationAccessError(403, "policy_principal_outside_organization")
        scope = rules.get("scope")
        if scope is not None:
            if not isinstance(scope, dict):
                raise OrganizationAccessError(422, "invalid_policy_scope")
            scope_type = scope.get("type") or scope.get("scope_type")
            scope_org = scope.get("organization_id")
            if scope_type not in {None, "organization"}:
                raise OrganizationAccessError(403, "policy_scope_outside_organization")
            if scope_org is not None and str(scope_org) != str(self.organization_id):
                raise OrganizationAccessError(403, "policy_scope_outside_organization")
        targets = rules.get("permissions")
        if not isinstance(targets, list) or not targets:
            raise OrganizationAccessError(422, "policy_permissions_required")
        if any(not isinstance(target, str) or "*" in target or ":" not in target for target in targets):
            raise OrganizationAccessError(422, "invalid_policy_permission_target")
        permission_map = {
            self._permission_key(permission): permission
            for permission in self.db.scalars(select(Permission)).all()
        }
        for target in targets:
            permission = permission_map.get(target)
            if permission is None:
                raise OrganizationAccessError(422, "unknown_policy_permission")
            self._assert_permission_delegable(permission)

    def _ensure_admin_remaining(self, *, exclude_principal_id: str | None = None) -> None:
        active_principals = {
            str(membership.user_id)
            for membership in self._memberships(include_removed=False)
            if membership.status == "active" and str(membership.user_id) != exclude_principal_id
        }
        if not active_principals:
            raise OrganizationAccessError(409, "last_organization_security_administrator")
        admin_principal = self.db.scalar(
            select(RoleAssignment.principal_id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                RoleAssignment.organization_id == self.organization_id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id.in_(active_principals),
                RoleAssignment.status == "active",
                RoleAssignment.scope_type == "organization",
                RoleAssignment.scope_id == str(self.organization_id),
                Role.organization_id == self.organization_id,
                Role.status == "active",
                Permission.resource == "organization.security",
                Permission.action == "administer",
            )
            .limit(1)
        )
        if admin_principal is None:
            raise OrganizationAccessError(409, "last_organization_security_administrator")

    def _audit(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        before_state = _safe_state(before or {})
        after_state = _safe_state(after or {})
        metadata = {
            "action": action,
            "result": "succeeded",
            "correlation_id": self.correlation_id,
            "postgresql_source_of_truth": True,
        }
        self.db.add(
            AuditEvent(
                organization_id=self.organization_id,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type=resource_type,
                resource_id=str(resource_id),
                summary=action,
                metadata_json=metadata,
            )
        )
        self.db.add(
            AuditHistory(
                organization_id=self.organization_id,
                entity_type=resource_type,
                entity_id=str(resource_id),
                action=action,
                before_state=before_state,
                after_state=after_state,
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _validate_code(self, value: str) -> str:
        code = value.strip().lower()
        if not CODE_PATTERN.fullmatch(code):
            raise OrganizationAccessError(422, "invalid_resource_code")
        return code

    def _permission_key(self, permission: Permission) -> str:
        return f"{self._permission_resource(permission)}:{self._permission_action(permission)}"

    def _permission_resource(self, permission: Permission) -> str:
        return permission.resource.strip().casefold()

    def _permission_action(self, permission: Permission) -> str:
        return permission.action.strip().casefold()

    def _permission_is_canonical(self, permission: Permission) -> bool:
        return (
            permission.resource == self._permission_resource(permission)
            and permission.action == self._permission_action(permission)
        )

    def _role_state(self, role: Role) -> dict[str, Any]:
        return {
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "status": role.status,
            "protected": self._role_is_protected(role),
        }

    def _assignment_state(self, assignment: RoleAssignment) -> dict[str, Any]:
        return {
            "role_id": assignment.role_id,
            "principal_id": assignment.principal_id,
            "status": assignment.status,
            "scope_type": assignment.scope_type,
            "scope_id": assignment.scope_id,
        }

    def _policy_state(self, policy: Policy) -> dict[str, Any]:
        return {
            "code": policy.code,
            "name": policy.name,
            "effect": policy.effect,
            "rules": policy.rules or {},
            "status": policy.status,
        }
