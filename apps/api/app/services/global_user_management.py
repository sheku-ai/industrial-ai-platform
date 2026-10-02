from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.models import (
    AuthenticationEvent,
    AuthSession,
    IdentityUser,
    OrganizationMembership,
    PasswordCredential,
)
from app.identity.passwords import PasswordManager, PasswordPolicyError
from app.identity.service import IdentityService, normalize_email, normalize_username
from app.models.audit import AuditEvent, AuditHistory
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission
from app.security.platform_roles import is_platform_role, platform_role_criteria

ADMIN_PERMISSION = "platform.security:administer"
GLOBAL_USER_LOCK = 7_241_005


class GlobalUserManagementError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class GlobalUserManagementService:
    """Governed identity and access lifecycle across the two PostgreSQL authorities."""

    def __init__(
        self,
        identity_db: Session,
        platform_db: Session,
        settings: Settings,
        *,
        actor_reference: str,
        correlation_id: str | None,
    ) -> None:
        self.identity_db = identity_db
        self.platform_db = platform_db
        self.settings = settings
        self.actor_reference = actor_reference
        self.correlation_id = correlation_id
        self.passwords = PasswordManager(settings)

    def _lock(self) -> None:
        self.identity_db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": GLOBAL_USER_LOCK})
        self.platform_db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": GLOBAL_USER_LOCK})

    def _user(self, user_id: uuid.UUID, *, lock: bool = False) -> IdentityUser:
        statement = select(IdentityUser).where(IdentityUser.id == user_id)
        user = self.identity_db.scalar(statement.with_for_update() if lock else statement)
        if user is None:
            raise GlobalUserManagementError(404, "identity_not_found")
        return user

    def _role(self, role_id: uuid.UUID, organization_id: uuid.UUID | None) -> Role:
        role = self.platform_db.get(Role, role_id)
        if role is None or role.status != "active" or role.organization_id != organization_id:
            raise GlobalUserManagementError(422, "role_not_delegable_in_scope")
        if organization_id is None and not is_platform_role(role, require_active=True):
            raise GlobalUserManagementError(422, "role_not_delegable_in_scope")
        return role

    def _permission_keys_by_role(self, role_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        if not role_ids:
            return {}
        rows = self.platform_db.execute(
            select(RolePermission.role_id, Permission.resource, Permission.action)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id.in_(role_ids))
            .order_by(RolePermission.role_id, Permission.resource, Permission.action)
        ).all()
        result: dict[uuid.UUID, list[str]] = {role_id: [] for role_id in role_ids}
        for role_id, resource, action in rows:
            result[role_id].append(f"{resource}:{action}")
        return result

    @staticmethod
    def _assigned_role_summary(
        assignment: RoleAssignment,
        role: Role | None,
        permission_keys: dict[uuid.UUID, list[str]],
    ) -> dict[str, Any]:
        platform_assignment = assignment.organization_id is None
        available = bool(
            role is not None
            and role.status == "active"
            and role.organization_id == assignment.organization_id
            and (not platform_assignment or is_platform_role(role, require_active=True))
        )
        return {
            "role_id": assignment.role_id,
            "name": role.name if role is not None else None,
            "code": role.code if role is not None else None,
            "status": role.status if role is not None else "unavailable",
            "scope": "platform" if platform_assignment else "organization",
            "is_system": role.is_system if role is not None else None,
            "permission_keys": permission_keys.get(assignment.role_id, []),
            "available": available,
            "inconsistency": None if available else "assigned_role_not_available",
        }

    def _audit(
        self,
        user_id: uuid.UUID,
        operation: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        outcome: str = "succeeded",
    ) -> None:
        safe_before = before or {}
        safe_after = after or {}
        metadata = {"operation": operation, "outcome": outcome, "correlation_id": self.correlation_id}
        self.platform_db.add(
            AuditEvent(
                organization_id=None,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type="global_identity",
                resource_id=str(user_id),
                summary=f"Global identity {operation} {outcome}.",
                metadata_json=metadata,
            )
        )
        self.platform_db.add(
            AuditHistory(
                organization_id=None,
                entity_type="global_identity",
                entity_id=str(user_id),
                action=operation,
                before_state=safe_before,
                after_state={**safe_after, "outcome": outcome},
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _commit(self) -> None:
        try:
            self.identity_db.commit()
            self.platform_db.commit()
        except IntegrityError as exc:
            self.identity_db.rollback()
            self.platform_db.rollback()
            raise GlobalUserManagementError(409, "global_identity_conflict") from exc

    def _assignment(
        self, user_id: uuid.UUID, role: Role, organization_id: uuid.UUID | None
    ) -> tuple[RoleAssignment, bool]:
        scope_type = "platform" if organization_id is None else "organization"
        scope_id = "platform" if organization_id is None else str(organization_id)
        assignment = self.platform_db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.role_id == role.id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id == str(user_id),
                RoleAssignment.scope_type == scope_type,
                RoleAssignment.scope_id == scope_id,
            )
        )
        if assignment is None:
            assignment = RoleAssignment(
                organization_id=organization_id,
                role_id=role.id,
                principal_type="user",
                principal_id=str(user_id),
                scope_type=scope_type,
                scope_id=scope_id,
                status="active",
                created_by=self.actor_reference,
                updated_by=self.actor_reference,
            )
            self.platform_db.add(assignment)
            return assignment, True
        changed = assignment.status != "active"
        assignment.status = "active"
        assignment.updated_by = self.actor_reference
        return assignment, changed

    def _other_active_admin_exists(self, excluded_user_id: uuid.UUID) -> bool:
        admin_role_ids = set(
            self.platform_db.scalars(
                select(RolePermission.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .join(Role, Role.id == RolePermission.role_id)
                .where(
                    Permission.resource == "platform.security",
                    Permission.action == "administer",
                    Role.status == "active",
                    *platform_role_criteria(),
                )
            ).all()
        )
        if not admin_role_ids:
            return False
        assigned_ids = {
            uuid.UUID(value)
            for value in self.platform_db.scalars(
                select(RoleAssignment.principal_id).where(
                    RoleAssignment.organization_id.is_(None),
                    RoleAssignment.scope_type == "platform",
                    RoleAssignment.status == "active",
                    RoleAssignment.role_id.in_(admin_role_ids),
                    RoleAssignment.principal_type == "user",
                    RoleAssignment.principal_id != str(excluded_user_id),
                )
            ).all()
        }
        return (
            bool(
                self.identity_db.scalar(
                    select(func.count(IdentityUser.id)).where(
                        IdentityUser.id.in_(assigned_ids), IdentityUser.status == "active"
                    )
                )
            )
            if assigned_ids
            else False
        )

    def _protect_last_admin(self, user_id: uuid.UUID, role_id: uuid.UUID | None = None) -> None:
        statement = (
            select(RoleAssignment.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                RoleAssignment.principal_id == str(user_id),
                RoleAssignment.principal_type == "user",
                RoleAssignment.scope_type == "platform",
                RoleAssignment.status == "active",
                Role.status == "active",
                *platform_role_criteria(),
                Permission.resource == "platform.security",
                Permission.action == "administer",
            )
        )
        if role_id is not None:
            statement = statement.where(RoleAssignment.role_id == role_id)
        affected_grant = self.platform_db.scalar(statement.limit(1))
        if affected_grant is None:
            return
        if role_id is not None:
            retained_grant = self.platform_db.scalar(
                select(RoleAssignment.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .join(RolePermission, RolePermission.role_id == RoleAssignment.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(
                    RoleAssignment.principal_id == str(user_id),
                    RoleAssignment.principal_type == "user",
                    RoleAssignment.scope_type == "platform",
                    RoleAssignment.status == "active",
                    RoleAssignment.role_id != role_id,
                    Role.status == "active",
                    *platform_role_criteria(),
                    Permission.resource == "platform.security",
                    Permission.action == "administer",
                )
                .limit(1)
            )
            if retained_grant is not None:
                return
        if not self._other_active_admin_exists(user_id):
            raise GlobalUserManagementError(409, "last_global_administrator_required")

    def _snapshot(self, user: IdentityUser) -> dict[str, Any]:
        assignments = list(
            self.platform_db.scalars(
                select(RoleAssignment)
                .where(
                    RoleAssignment.principal_type == "user",
                    RoleAssignment.principal_id == str(user.id),
                    RoleAssignment.status == "active",
                )
                .order_by(RoleAssignment.created_at, RoleAssignment.id)
            ).all()
        )
        role_ids = {assignment.role_id for assignment in assignments}
        roles_by_id = {
            role.id: role
            for role in self.platform_db.scalars(select(Role).where(Role.id.in_(role_ids))).all()
        } if role_ids else {}
        permission_keys = self._permission_keys_by_role(role_ids)
        memberships = list(
            self.identity_db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.status == "active",
                )
            ).all()
        )
        organization_names = {item.id: item.name for item in self.platform_db.scalars(select(Organization)).all()}
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email_display,
            "status": user.status,
            "must_change_password": user.must_change_password,
            "active_sessions": int(
                self.identity_db.scalar(
                    select(func.count(AuthSession.id)).where(
                        AuthSession.user_id == user.id,
                        AuthSession.revoked_at.is_(None),
                        AuthSession.idle_expires_at > datetime.now(UTC),
                        AuthSession.absolute_expires_at > datetime.now(UTC),
                    )
                )
                or 0
            ),
            "global_roles": [
                self._assigned_role_summary(assignment, roles_by_id.get(assignment.role_id), permission_keys)
                for assignment in assignments
                if assignment.organization_id is None
            ],
            "memberships": [
                {
                    "membership_id": membership.id,
                    "organization_id": membership.organization_id,
                    "organization_name": organization_names.get(membership.organization_id, ""),
                    "roles": [
                        self._assigned_role_summary(
                            assignment,
                            roles_by_id.get(assignment.role_id),
                            permission_keys,
                        )
                        for assignment in assignments
                        if assignment.organization_id == membership.organization_id
                    ],
                }
                for membership in memberships
            ],
        }

    def runtime(self) -> dict[str, Any]:
        users = list(
            self.identity_db.scalars(select(IdentityUser).order_by(IdentityUser.username, IdentityUser.id)).all()
        )
        organizations = list(
            self.platform_db.scalars(
                select(Organization).where(Organization.status == "active").order_by(Organization.name)
            ).all()
        )
        roles = list(self.platform_db.scalars(select(Role).where(Role.status == "active").order_by(Role.name)).all())
        role_permission_keys = self._permission_keys_by_role({role.id for role in roles})
        return {
            "users": [self._snapshot(user) for user in users],
            "organizations": [{"organization_id": item.id, "name": item.name} for item in organizations],
            "global_roles": [
                {
                    "role_id": item.id,
                    "name": item.name,
                    "code": item.code,
                    "status": item.status,
                    "scope": "platform",
                    "is_system": item.is_system,
                    "permission_keys": role_permission_keys.get(item.id, []),
                    "available": True,
                    "inconsistency": None,
                }
                for item in roles
                if is_platform_role(item, require_active=True)
            ],
            "organization_roles": [
                {"role_id": item.id, "organization_id": item.organization_id, "name": item.name}
                for item in roles
                if item.organization_id is not None
            ],
            "capabilities": {"read": True, "administer": True},
            "postgresql_source_of_truth": True,
        }

    def create(self, *, username: str, display_name: str, email: str, temporary_password: str) -> dict[str, Any]:
        self._lock()
        try:
            normalized_username = normalize_username(username)
            normalized_email = normalize_email(email)
            password_hash = self.passwords.hash_password(temporary_password)
        except ValueError as exc:
            raise GlobalUserManagementError(422, str(exc)) from exc
        normalized_display_name = display_name.strip()
        if not normalized_display_name:
            raise GlobalUserManagementError(422, "display_name_required")
        if (
            self.identity_db.scalar(
                select(IdentityUser.id).where(
                    (IdentityUser.username == normalized_username) | (IdentityUser.email_normalized == normalized_email)
                )
            )
            is not None
        ):
            raise GlobalUserManagementError(409, "identity_already_exists")
        user = IdentityUser(
            username=normalized_username,
            email_normalized=normalized_email,
            email_display=email.strip(),
            display_name=normalized_display_name,
            status="active",
            must_change_password=True,
        )
        self.identity_db.add(user)
        self.identity_db.flush()
        self.identity_db.add(
            PasswordCredential(
                user_id=user.id,
                password_hash=password_hash,
                algorithm=self.passwords.algorithm,
                parameters=self.passwords.parameters,
            )
        )
        self._audit(user.id, "identity.created", after={"username": user.username, "status": user.status})
        self._commit()
        return {"operation": "identity.created", "outcome": "created", "user": self._snapshot(user)}

    def update(self, user_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        before = {"username": user.username, "email": user.email_display, "display_name": user.display_name}
        try:
            if "username" in changes:
                user.username = normalize_username(changes["username"])
            if "email" in changes:
                user.email_normalized = normalize_email(changes["email"])
                user.email_display = changes["email"].strip()
        except ValueError as exc:
            raise GlobalUserManagementError(422, str(exc)) from exc
        if "display_name" in changes:
            display_name = changes["display_name"].strip()
            if not display_name:
                raise GlobalUserManagementError(422, "display_name_required")
            user.display_name = display_name
        self._audit(
            user.id,
            "identity.updated",
            before=before,
            after={"username": user.username, "email": user.email_display, "display_name": user.display_name},
        )
        self._commit()
        return {"operation": "identity.updated", "outcome": "updated", "user": self._snapshot(user)}

    def reset_password(self, user_id: uuid.UUID, temporary_password: str) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        IdentityService(self.identity_db, self.settings).lock_user_session_lifecycle(user.id)
        try:
            password_hash = self.passwords.hash_password(temporary_password)
        except PasswordPolicyError as exc:
            raise GlobalUserManagementError(422, str(exc)) from exc
        credential = self.identity_db.get(PasswordCredential, user.id)
        if credential is None:
            credential = PasswordCredential(
                user_id=user.id,
                password_hash=password_hash,
                algorithm=self.passwords.algorithm,
                parameters=self.passwords.parameters,
            )
            self.identity_db.add(credential)
        else:
            credential.password_hash = password_hash
            credential.algorithm = self.passwords.algorithm
            credential.parameters = self.passwords.parameters
            credential.password_changed_at = datetime.now(UTC)
        user.must_change_password = True
        self._revoke(user, "password_reset")
        self._audit(user.id, "credential.password_reset", after={"must_change_password": True})
        self._commit()
        return {"operation": "credential.password_reset", "outcome": "updated", "user": self._snapshot(user)}

    def _revoke(self, user: IdentityUser, reason: str) -> int:
        return IdentityService(self.identity_db, self.settings).revoke_user_sessions(
            user,
            reason=reason,
            actor_reference=self.actor_reference,
        )

    def revoke_sessions(self, user_id: uuid.UUID) -> dict[str, Any]:
        user = self._user(user_id, lock=True)
        count = self._revoke(user, "administrative_revocation")
        self._audit(user.id, "sessions.revoked", after={"revoked_session_count": count})
        self._commit()
        return {"operation": "sessions.revoked", "outcome": "updated", "user": self._snapshot(user)}

    def set_status(self, user_id: uuid.UUID, active: bool) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        if not active:
            IdentityService(self.identity_db, self.settings).lock_user_session_lifecycle(user.id)
        if not active:
            self._protect_last_admin(user.id)
        user.status = "active" if active else "suspended"
        user.disabled_at = None if active else datetime.now(UTC)
        if not active:
            self._revoke(user, "identity_deactivated")
        operation = "identity.activated" if active else "identity.deactivated"
        self._audit(user.id, operation, after={"status": user.status})
        self._commit()
        return {"operation": operation, "outcome": "updated", "user": self._snapshot(user)}

    def set_role(
        self, user_id: uuid.UUID, role_id: uuid.UUID, organization_id: uuid.UUID | None, active: bool
    ) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        role = self._role(role_id, organization_id)
        if active:
            if (
                organization_id is not None
                and self.identity_db.scalar(
                    select(OrganizationMembership.id)
                    .where(
                        OrganizationMembership.user_id == user.id,
                        OrganizationMembership.organization_id == organization_id,
                        OrganizationMembership.status == "active",
                    )
                    .limit(1)
                )
                is None
            ):
                raise GlobalUserManagementError(409, "organization_membership_required")
            self._assignment(user.id, role, organization_id)
        else:
            if organization_id is None:
                self._protect_last_admin(user.id, role.id)
            assignment = self.platform_db.scalar(
                select(RoleAssignment).where(
                    RoleAssignment.role_id == role.id,
                    RoleAssignment.principal_id == str(user.id),
                    RoleAssignment.principal_type == "user",
                    RoleAssignment.status == "active",
                )
            )
            if assignment is not None:
                assignment.status = "inactive"
                assignment.updated_by = self.actor_reference
        operation = "role.assigned" if active else "role.removed"
        self._audit(
            user.id,
            operation,
            after={"role_id": str(role.id), "scope": "platform" if organization_id is None else "organization"},
        )
        self._commit()
        return {"operation": operation, "outcome": "updated", "user": self._snapshot(user)}

    def set_membership(
        self, user_id: uuid.UUID, organization_id: uuid.UUID, role_id: uuid.UUID | None, active: bool
    ) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        organization = self.platform_db.get(Organization, organization_id)
        if organization is None or organization.status != "active":
            raise GlobalUserManagementError(422, "organization_not_available")
        memberships = list(
            self.identity_db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id, OrganizationMembership.organization_id == organization_id
                )
            ).all()
        )
        if active:
            if role_id is None:
                raise GlobalUserManagementError(422, "role_required")
            role = self._role(role_id, organization_id)
            membership = next((item for item in memberships if item.role_id == role.id), None)
            for item in memberships:
                if item is not membership and item.status == "active":
                    item.status = "removed"
                    item.removed_at = datetime.now(UTC)
            if membership is None:
                self.identity_db.add(
                    OrganizationMembership(
                        user_id=user.id, organization_id=organization_id, role_id=role.id, status="active"
                    )
                )
            else:
                membership.status = "active"
                membership.suspended_at = None
                membership.removed_at = None
            self._assignment(user.id, role, organization_id)
        else:
            for membership in memberships:
                membership.status = "removed"
                membership.removed_at = datetime.now(UTC)
            for assignment in self.platform_db.scalars(
                select(RoleAssignment).where(
                    RoleAssignment.principal_id == str(user.id),
                    RoleAssignment.organization_id == organization_id,
                    RoleAssignment.status == "active",
                )
            ).all():
                assignment.status = "inactive"
                assignment.updated_by = self.actor_reference
        operation = "membership.assigned" if active else "membership.removed"
        self._audit(user.id, operation, after={"organization_id": str(organization_id)})
        self._commit()
        return {"operation": operation, "outcome": "updated", "user": self._snapshot(user)}

    def delete(self, user_id: uuid.UUID) -> dict[str, Any]:
        self._lock()
        user = self._user(user_id, lock=True)
        try:
            self._protect_last_admin(user.id)
        except GlobalUserManagementError:
            self._audit(
                user.id, "identity.delete_rejected", after={"reason": "last_global_administrator"}, outcome="conflict"
            )
            self.platform_db.commit()
            raise
        identity_dependencies = sum(
            int(self.identity_db.scalar(select(func.count(model.id)).where(model.user_id == user.id)) or 0)
            for model in (OrganizationMembership, AuthSession, AuthenticationEvent)
        )
        platform_dependencies = int(
            self.platform_db.scalar(
                select(func.count(RoleAssignment.id)).where(
                    RoleAssignment.principal_id == str(user.id), RoleAssignment.principal_type == "user"
                )
            )
            or 0
        )
        platform_dependencies += int(
            self.platform_db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.resource_type == "global_identity", AuditEvent.resource_id == str(user.id)
                )
            )
            or 0
        )
        if identity_dependencies or platform_dependencies:
            self._audit(user.id, "identity.delete_rejected", after={"reason": "dependencies_exist"}, outcome="conflict")
            self.platform_db.commit()
            raise GlobalUserManagementError(409, "identity_has_dependencies_deactivate_instead")
        username = user.username
        self.identity_db.delete(user)
        self.identity_db.commit()
        self._audit(user_id, "identity.deleted", before={"username": username})
        self.platform_db.commit()
        return {"operation": "identity.deleted", "outcome": "deleted", "user": None}
