from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, text, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.security.platform_roles import platform_role_criteria
from app.security.resource_scope import ResourceScope
from app.services.authorization import AuthorizationService

GLOBAL_ROLE_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
GLOBAL_ROLE_MANAGEMENT_MARKER = "security_management"


class GlobalRoleManagementError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _issue(code: str, message: str, *, component: str = "security_management") -> dict[str, Any]:
    return {"code": code, "message": message, "component": component}


def _permission_key(permission: Permission) -> str:
    return f"{permission.resource}:{permission.action}"


def _permission_to_dict(permission: Permission) -> dict[str, Any]:
    return {
        "id": permission.id,
        "resource": permission.resource,
        "action": permission.action,
        "description": permission.description,
        "key": _permission_key(permission),
        "created_at": permission.created_at,
        "updated_at": permission.updated_at,
        "created_by": permission.created_by,
        "updated_by": permission.updated_by,
    }


def _role_to_dict(role: Role) -> dict[str, Any]:
    return {
        "id": role.id,
        "organization_id": role.organization_id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "status": role.status,
        "config": role.config or {},
        "created_at": role.created_at,
        "updated_at": role.updated_at,
        "created_by": role.created_by,
        "updated_by": role.updated_by,
    }


def _policy_to_dict(policy: Policy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "organization_id": policy.organization_id,
        "code": policy.code,
        "name": policy.name,
        "effect": policy.effect,
        "rules": policy.rules or {},
        "status": policy.status,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
        "created_by": policy.created_by,
        "updated_by": policy.updated_by,
    }


def _assignment_to_dict(assignment: RoleAssignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "organization_id": assignment.organization_id,
        "role_id": assignment.role_id,
        "principal_type": assignment.principal_type,
        "principal_id": assignment.principal_id,
        "scope_type": assignment.scope_type,
        "scope_id": assignment.scope_id,
        "status": assignment.status,
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
        "created_by": assignment.created_by,
        "updated_by": assignment.updated_by,
    }


def _organization_filter(model: Any, organization_id: uuid.UUID | None):
    if organization_id is None:
        return model.organization_id.is_(None)
    return or_(model.organization_id.is_(None), model.organization_id == organization_id)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise


def build_security_management_readiness(db: Session) -> dict[str, Any]:
    roles_count = int(db.scalar(select(func.count(Role.id))) or 0)
    permissions_count = int(db.scalar(select(func.count(Permission.id))) or 0)
    policies_count = int(db.scalar(select(func.count(Policy.id))) or 0)
    assignments_count = int(db.scalar(select(func.count(RoleAssignment.id))) or 0)
    active_roles_count = int(db.scalar(select(func.count(Role.id)).where(Role.status == "active")) or 0)
    active_policies_count = int(db.scalar(select(func.count(Policy.id)).where(Policy.status == "active")) or 0)
    active_assignments_count = int(
        db.scalar(select(func.count(RoleAssignment.id)).where(RoleAssignment.status == "active")) or 0
    )
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    if roles_count == 0:
        warnings.append(_issue("roles_not_configured", "No roles are configured."))
    if permissions_count == 0:
        warnings.append(_issue("permissions_not_configured", "No permissions are configured."))
    if assignments_count == 0:
        warnings.append(_issue("assignments_not_configured", "No role assignments are configured."))
    return {
        "roles_count": roles_count,
        "permissions_count": permissions_count,
        "policies_count": policies_count,
        "assignments_count": assignments_count,
        "active_roles_count": active_roles_count,
        "active_permissions_count": permissions_count,
        "active_policies_count": active_policies_count,
        "active_assignments_count": active_assignments_count,
        "has_roles": roles_count > 0,
        "has_permissions": permissions_count > 0,
        "has_assignments": assignments_count > 0,
        "security_management_ready": roles_count > 0 and permissions_count > 0,
        "authentication_provider_ready": False,
        "jwt_ready": False,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "postgresql_source_of_truth": True,
    }


def list_roles(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    include_global: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(Role)
    if organization_id is not None:
        statement = statement.where(
            _organization_filter(Role, organization_id)
            if include_global
            else Role.organization_id == organization_id
        )
    statement = statement.order_by(Role.organization_id.asc().nullsfirst(), Role.code.asc(), Role.id.asc())
    return [_role_to_dict(item) for item in db.scalars(statement.offset(skip).limit(limit)).all()]


def get_role(db: Session, role_id: uuid.UUID) -> Role | None:
    return db.get(Role, role_id)


def create_role(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    role = Role(**data)
    db.add(role)
    _commit(db)
    db.refresh(role)
    return _role_to_dict(role)


def update_role(db: Session, role: Role, data: dict[str, Any]) -> dict[str, Any]:
    for key, value in data.items():
        if value is not None:
            setattr(role, key, value)
    db.add(role)
    _commit(db)
    db.refresh(role)
    return _role_to_dict(role)


def list_permissions(db: Session, *, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    statement = select(Permission).order_by(Permission.resource.asc(), Permission.action.asc(), Permission.id.asc())
    return [_permission_to_dict(item) for item in db.scalars(statement.offset(skip).limit(limit)).all()]


def create_permission(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    data = {
        **data,
        "resource": str(data["resource"]).strip().casefold(),
        "action": str(data["action"]).strip().casefold(),
    }
    statement = select(Permission).where(
        Permission.resource == data["resource"],
        Permission.action == data["action"],
    )
    existing = db.scalar(statement)
    if existing is not None:
        return _permission_to_dict(existing)
    permission = Permission(**data)
    db.add(permission)
    _commit(db)
    db.refresh(permission)
    return _permission_to_dict(permission)


def list_role_permissions(db: Session, role: Role) -> list[dict[str, Any]]:
    statement = (
        select(RolePermission, Permission)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.resource.asc(), Permission.action.asc(), Permission.id.asc())
    )
    return [
        {
            "id": role_permission.id,
            "role_id": role_permission.role_id,
            "permission_id": role_permission.permission_id,
            "permission": _permission_to_dict(permission),
            "attached": True,
            "created_at": role_permission.created_at,
            "updated_at": role_permission.updated_at,
        }
        for role_permission, permission in db.execute(statement).all()
    ]


def attach_role_permission(db: Session, role: Role, permission: Permission) -> dict[str, Any]:
    existing = db.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    if existing is None:
        now = datetime.now(UTC)
        existing = RolePermission(role_id=role.id, permission_id=permission.id, created_at=now, updated_at=now)
        db.add(existing)
        _commit(db)
        db.refresh(existing)
    return {
        "id": existing.id,
        "role_id": existing.role_id,
        "permission_id": existing.permission_id,
        "permission": _permission_to_dict(permission),
        "attached": True,
        "created_at": existing.created_at,
        "updated_at": existing.updated_at,
    }


def remove_role_permission(db: Session, role: Role, permission: Permission) -> bool:
    existing = db.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def list_policies(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    include_global: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(Policy)
    if organization_id is not None:
        statement = statement.where(
            _organization_filter(Policy, organization_id)
            if include_global
            else Policy.organization_id == organization_id
        )
    statement = statement.order_by(Policy.organization_id.asc().nullsfirst(), Policy.code.asc(), Policy.id.asc())
    return [_policy_to_dict(item) for item in db.scalars(statement.offset(skip).limit(limit)).all()]


def get_policy(db: Session, policy_id: uuid.UUID) -> Policy | None:
    return db.get(Policy, policy_id)


def create_policy(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    policy = Policy(**data)
    db.add(policy)
    _commit(db)
    db.refresh(policy)
    return _policy_to_dict(policy)


def update_policy(db: Session, policy: Policy, data: dict[str, Any]) -> dict[str, Any]:
    for key, value in data.items():
        if value is not None:
            setattr(policy, key, value)
    db.add(policy)
    _commit(db)
    db.refresh(policy)
    return _policy_to_dict(policy)


def list_role_assignments(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    include_global: bool = True,
    principal_type: str | None = None,
    principal_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(RoleAssignment)
    if organization_id is not None:
        statement = statement.where(
            _organization_filter(RoleAssignment, organization_id)
            if include_global
            else RoleAssignment.organization_id == organization_id
        )
    if principal_type:
        statement = statement.where(RoleAssignment.principal_type == principal_type)
    if principal_id:
        statement = statement.where(RoleAssignment.principal_id == principal_id)
    statement = statement.order_by(
        RoleAssignment.organization_id.asc().nullsfirst(),
        RoleAssignment.principal_type.asc(),
        RoleAssignment.principal_id.asc(),
        RoleAssignment.id.asc(),
    )
    return [_assignment_to_dict(item) for item in db.scalars(statement.offset(skip).limit(limit)).all()]


def get_assignment(db: Session, assignment_id: uuid.UUID) -> RoleAssignment | None:
    return db.get(RoleAssignment, assignment_id)


def create_role_assignment(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    assignment = RoleAssignment(**data)
    db.add(assignment)
    _commit(db)
    db.refresh(assignment)
    return _assignment_to_dict(assignment)


def update_role_assignment(db: Session, assignment: RoleAssignment, data: dict[str, Any]) -> dict[str, Any]:
    for key, value in data.items():
        if value is not None:
            setattr(assignment, key, value)
    db.add(assignment)
    _commit(db)
    db.refresh(assignment)
    return _assignment_to_dict(assignment)


class GlobalRoleManagementService:
    """Governed, platform-scoped lifecycle for configurable global roles."""

    def __init__(
        self,
        db: Session,
        *,
        actor_reference: str,
        correlation_id: str | None,
    ) -> None:
        self.db = db
        self.actor_reference = actor_reference
        self.correlation_id = correlation_id

    def list_roles(self) -> list[dict[str, Any]]:
        roles = list(
            self.db.scalars(
                select(Role)
                .where(*platform_role_criteria())
                .order_by(Role.code, Role.id)
            ).all()
        )
        return [self._response(role) for role in roles]

    def reconcile(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        permission_keys: list[str],
    ) -> dict[str, Any]:
        normalized_code = self._normalize_code(code)
        normalized_name = self._normalize_name(name)
        normalized_description = self._normalize_description(description)
        normalized_permission_keys = self._normalize_permission_keys(permission_keys)
        self._lock(normalized_code)

        permissions = self._permissions(normalized_permission_keys)
        missing = sorted(set(normalized_permission_keys) - set(permissions))
        if missing:
            self._reject(
                code=normalized_code,
                operation="global_role.reconcile",
                outcome="failure",
                error_code="unknown_permission",
                permission_keys=normalized_permission_keys,
                status_code=422,
            )

        roles = self._roles_by_code(normalized_code, lock=True)
        if len(roles) > 1:
            self._reject(
                code=normalized_code,
                operation="global_role.reconcile",
                outcome="conflict",
                error_code="ambiguous_global_role_code",
                permission_keys=normalized_permission_keys,
                status_code=409,
                role_ids=[str(role.id) for role in roles],
            )

        if roles:
            role = roles[0]
            current_permission_keys = self._permission_keys(role.id)
            conflicts = self._specification_conflicts(
                role,
                name=normalized_name,
                description=normalized_description,
                permission_keys=normalized_permission_keys,
                current_permission_keys=current_permission_keys,
            )
            if conflicts:
                self._reject(
                    code=normalized_code,
                    operation="global_role.reconcile",
                    outcome="conflict",
                    error_code="global_role_specification_conflict",
                    permission_keys=normalized_permission_keys,
                    status_code=409,
                    role=role,
                    before=self._role_state(role, current_permission_keys),
                    details={"conflicting_fields": conflicts},
                )
            state = self._role_state(role, current_permission_keys)
            self._audit(
                role=role,
                operation="global_role.reconcile",
                outcome="idempotent",
                permission_keys=current_permission_keys,
                before=state,
                after=state,
            )
            self.db.commit()
            return self._response(role, permission_keys=current_permission_keys, outcome="idempotent")

        role = Role(
            organization_id=None,
            code=normalized_code,
            name=normalized_name,
            description=normalized_description,
            is_system=False,
            status="active",
            config={
                "scope": "platform",
                "managed_by": GLOBAL_ROLE_MANAGEMENT_MARKER,
                "configurable": True,
            },
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.db.add(role)
        self.db.flush()
        now = datetime.now(UTC)
        for permission_key in normalized_permission_keys:
            permission = permissions[permission_key]
            self.db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id,
                    created_at=now,
                    updated_at=now,
                    created_by=self.actor_reference,
                    updated_by=self.actor_reference,
                )
            )
        self.db.flush()
        self._audit(
            role=role,
            operation="global_role.reconcile",
            outcome="created",
            permission_keys=normalized_permission_keys,
            after=self._role_state(role, normalized_permission_keys),
        )
        self.db.commit()
        return self._response(role, permission_keys=normalized_permission_keys, outcome="created")

    def deactivate(self, code: str) -> dict[str, Any]:
        return self._set_status(code, "inactive")

    def activate(self, code: str) -> dict[str, Any]:
        return self._set_status(code, "active")

    def _set_status(self, code: str, target_status: str) -> dict[str, Any]:
        normalized_code = self._normalize_code(code)
        self._lock(normalized_code)
        roles = self._roles_by_code(normalized_code, lock=True)
        operation = f"global_role.{target_status}"
        if not roles:
            self._reject(
                code=normalized_code,
                operation=operation,
                outcome="failure",
                error_code="global_role_not_found",
                permission_keys=[],
                status_code=404,
            )
        if len(roles) > 1:
            self._reject(
                code=normalized_code,
                operation=operation,
                outcome="conflict",
                error_code="ambiguous_global_role_code",
                permission_keys=[],
                status_code=409,
                role_ids=[str(role.id) for role in roles],
            )

        role = roles[0]
        permission_keys = self._permission_keys(role.id)
        if not self._is_managed(role):
            self._reject(
                code=normalized_code,
                operation=operation,
                outcome="conflict",
                error_code="global_role_not_configurable",
                permission_keys=permission_keys,
                status_code=409,
                role=role,
                before=self._role_state(role, permission_keys),
            )

        before = self._role_state(role, permission_keys)
        if role.status == target_status:
            self._audit(
                role=role,
                operation=operation,
                outcome="idempotent",
                permission_keys=permission_keys,
                before=before,
                after=before,
            )
            self.db.commit()
            return self._status_response(role, permission_keys, "idempotent")

        role.status = target_status
        role.updated_by = self.actor_reference
        self.db.flush()
        after = self._role_state(role, permission_keys)
        self._audit(
            role=role,
            operation=operation,
            outcome="updated",
            permission_keys=permission_keys,
            before=before,
            after=after,
        )
        self.db.commit()
        return self._status_response(role, permission_keys, "updated")

    def _lock(self, code: str) -> None:
        digest = hashlib.sha256(f"global-role|{code}".encode()).digest()
        lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
        self.db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    def _roles_by_code(self, code: str, *, lock: bool) -> list[Role]:
        statement = select(Role).where(Role.organization_id.is_(None), Role.code == code).order_by(Role.id)
        if lock:
            statement = statement.with_for_update()
        return list(self.db.scalars(statement).all())

    def _permissions(self, permission_keys: list[str]) -> dict[str, Permission]:
        pairs = [tuple(permission_key.split(":", 1)) for permission_key in permission_keys]
        statement = select(Permission).where(tuple_(Permission.resource, Permission.action).in_(pairs))
        return {_permission_key(permission): permission for permission in self.db.scalars(statement).all()}

    def _permission_keys(self, role_id: uuid.UUID) -> list[str]:
        statement = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.resource, Permission.action, Permission.id)
        )
        return sorted({_permission_key(permission) for permission in self.db.scalars(statement).all()})

    def _specification_conflicts(
        self,
        role: Role,
        *,
        name: str,
        description: str | None,
        permission_keys: list[str],
        current_permission_keys: list[str],
    ) -> list[str]:
        config = role.config if isinstance(role.config, dict) else {}
        checks = {
            "name": role.name == name,
            "description": role.description == description,
            "scope": role.organization_id is None and config.get("scope") == "platform",
            "status": role.status == "active",
            "is_system": role.is_system is False,
            "configurable": self._is_managed(role),
            "permission_keys": current_permission_keys == permission_keys,
        }
        return sorted(field for field, matches in checks.items() if not matches)

    def _is_managed(self, role: Role) -> bool:
        config = role.config if isinstance(role.config, dict) else {}
        return bool(
            role.organization_id is None
            and role.is_system is False
            and config.get("scope") == "platform"
            and config.get("managed_by") == GLOBAL_ROLE_MANAGEMENT_MARKER
            and config.get("configurable") is True
        )

    def _normalize_code(self, value: str) -> str:
        code = str(value or "").strip().casefold()
        if not code or len(code) > 128 or not GLOBAL_ROLE_CODE_PATTERN.fullmatch(code):
            raise GlobalRoleManagementError(422, "invalid_global_role_code")
        return code

    def _normalize_name(self, value: str) -> str:
        name = str(value or "").strip()
        if not name or len(name) > 255:
            raise GlobalRoleManagementError(422, "invalid_global_role_name")
        return name

    def _normalize_description(self, value: str | None) -> str | None:
        if value is None:
            return None
        description = str(value).strip() or None
        if description is not None and len(description) > 4_000:
            raise GlobalRoleManagementError(422, "invalid_global_role_description")
        return description

    def _normalize_permission_keys(self, values: list[str]) -> list[str]:
        normalized: set[str] = set()
        for value in values:
            permission_key = str(value or "").strip().casefold()
            if (
                not permission_key
                or "*" in permission_key
                or permission_key.count(":") != 1
                or any(not part for part in permission_key.split(":", 1))
            ):
                raise GlobalRoleManagementError(422, "invalid_permission_key")
            normalized.add(permission_key)
        if not normalized:
            raise GlobalRoleManagementError(422, "permission_keys_required")
        return sorted(normalized)

    def _reject(
        self,
        *,
        code: str,
        operation: str,
        outcome: str,
        error_code: str,
        permission_keys: list[str],
        status_code: int,
        role: Role | None = None,
        role_ids: list[str] | None = None,
        before: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit(
            role=role,
            role_code=code,
            operation=operation,
            outcome=outcome,
            permission_keys=permission_keys,
            before=before,
            details={
                "error_code": error_code,
                **({"role_ids": role_ids} if role_ids else {}),
                **(details or {}),
            },
        )
        self.db.commit()
        raise GlobalRoleManagementError(status_code, error_code)

    def _audit(
        self,
        *,
        operation: str,
        outcome: str,
        permission_keys: list[str],
        role: Role | None = None,
        role_code: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        code = role.code if role is not None else str(role_code)
        resource_id = str(role.id) if role is not None else code
        metadata = {
            "operation": operation,
            "result": outcome,
            "role_id": str(role.id) if role is not None else None,
            "role_code": code,
            "scope": "platform",
            "permission_keys": permission_keys,
            "correlation_id": self.correlation_id,
            "postgresql_source_of_truth": True,
            **(details or {}),
        }
        self.db.add(
            AuditEvent(
                organization_id=None,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type="global_security_role",
                resource_id=resource_id,
                summary=operation,
                metadata_json=metadata,
            )
        )
        self.db.add(
            AuditHistory(
                organization_id=None,
                entity_type="global_security_role",
                entity_id=resource_id,
                action=operation,
                before_state=before or {},
                after_state=after or {},
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _role_state(self, role: Role, permission_keys: list[str]) -> dict[str, Any]:
        return {
            "role_id": str(role.id),
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "scope": "platform",
            "status": role.status,
            "is_system": role.is_system,
            "configurable": self._is_managed(role),
            "permission_keys": permission_keys,
        }

    def _response(
        self,
        role: Role,
        *,
        permission_keys: list[str] | None = None,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        resolved_permission_keys = permission_keys if permission_keys is not None else self._permission_keys(role.id)
        return {
            **self._role_state(role, resolved_permission_keys),
            "outcome": outcome,
        }

    def _status_response(self, role: Role, permission_keys: list[str], outcome: str) -> dict[str, Any]:
        return self._response(role, permission_keys=permission_keys, outcome=outcome)


def resolve_principal_permissions(
    db: Session,
    *,
    principal_type: str,
    principal_id: str,
    organization_id: uuid.UUID | None,
    scope: str,
    scope_id: str | None = None,
) -> dict[str, Any]:
    resource_scope = ResourceScope.from_values(
        scope_type=scope,
        organization_id=organization_id,
        resource_id=scope_id,
    )
    service = AuthorizationService(db)
    permissions = sorted(
        service.resolve_permissions_for_scope(
            principal_id=principal_id,
            principal_type=principal_type,
            resource_scope=resource_scope,
        )
    )
    assignments = _principal_assignments(
        db,
        principal_type=principal_type,
        principal_id=principal_id,
        resource_scope=resource_scope,
    )
    roles = _principal_roles(db, assignments)
    policy_result = service.policy_evaluator.evaluate(
        policies=service._candidate_policies(resource_scope),
        resource_scope=resource_scope,
        principal_type=principal_type,
        principal_id=principal_id,
        assigned_permissions=service._resolve_role_assignment_permissions(
            principal_id=principal_id,
            principal_type=principal_type,
            resource_scope=resource_scope,
        ),
    )
    return {
        "principal_type": principal_type,
        "principal_id": principal_id,
        "organization_id": organization_id,
        "scope": resource_scope.scope_type.value,
        "scope_id": resource_scope.scope_id,
        "permissions": permissions,
        "roles": roles,
        "assignments": [_assignment_summary(item) for item in assignments],
        "policies_applied": list(policy_result.matched_policy_codes),
        "access_management_ready": bool(permissions or roles or assignments),
        "jwt_required": False,
        "jwt_used": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "postgresql_source_of_truth": True,
    }


def _principal_assignments(
    db: Session,
    *,
    principal_type: str,
    principal_id: str,
    resource_scope: ResourceScope,
) -> list[RoleAssignment]:
    statement = (
        select(RoleAssignment)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(
            RoleAssignment.principal_type == principal_type,
            RoleAssignment.principal_id == principal_id,
            RoleAssignment.status == "active",
            Role.status == "active",
        )
    )
    if resource_scope.scope_type.value == "platform":
        statement = statement.where(
            RoleAssignment.organization_id.is_(None),
            *platform_role_criteria(),
            RoleAssignment.scope_type == "platform",
            or_(RoleAssignment.scope_id.is_(None), RoleAssignment.scope_id == resource_scope.scope_id),
        )
    elif resource_scope.scope_type.value == "organization":
        statement = statement.where(
            or_(
                RoleAssignment.organization_id == resource_scope.organization_id,
                RoleAssignment.organization_id.is_(None),
            ),
            or_(Role.organization_id == resource_scope.organization_id, Role.organization_id.is_(None)),
            or_(RoleAssignment.scope_type.is_(None), RoleAssignment.scope_type == "organization"),
            or_(RoleAssignment.scope_id.is_(None), RoleAssignment.scope_id == resource_scope.scope_id),
        )
    else:
        statement = statement.where(
            or_(
                RoleAssignment.organization_id == resource_scope.organization_id,
                RoleAssignment.organization_id.is_(None),
            ),
            or_(Role.organization_id == resource_scope.organization_id, Role.organization_id.is_(None)),
            or_(RoleAssignment.scope_type.is_(None), RoleAssignment.scope_type.in_(("organization", "workload"))),
            or_(
                RoleAssignment.scope_id.is_(None),
                RoleAssignment.scope_id.in_((str(resource_scope.organization_id), resource_scope.scope_id)),
            ),
        )
    return list(db.scalars(statement.order_by(RoleAssignment.created_at.asc(), RoleAssignment.id.asc())).all())


def _principal_roles(db: Session, assignments: list[RoleAssignment]) -> list[dict[str, Any]]:
    role_ids = list(dict.fromkeys(item.role_id for item in assignments))
    if not role_ids:
        return []
    roles = list(db.scalars(select(Role).where(Role.id.in_(role_ids)).order_by(Role.code.asc(), Role.id.asc())).all())
    return [
        {
            "role_id": role.id,
            "code": role.code,
            "name": role.name,
            "status": role.status,
            "organization_id": role.organization_id,
        }
        for role in roles
    ]


def _assignment_summary(assignment: RoleAssignment) -> dict[str, Any]:
    return {
        "assignment_id": assignment.id,
        "role_id": assignment.role_id,
        "organization_id": assignment.organization_id,
        "principal_type": assignment.principal_type,
        "principal_id": assignment.principal_id,
        "scope_type": assignment.scope_type,
        "scope_id": assignment.scope_id,
        "status": assignment.status,
    }
