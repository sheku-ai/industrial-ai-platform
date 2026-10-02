from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.security.platform_roles import platform_role_criteria
from app.security.policy_evaluator import PolicyEvaluator
from app.security.resource_scope import ResourceScope, ResourceScopeType

AuthorizationScope = Literal["platform", "organization", "workload"]


@dataclass(frozen=True)
class PermissionGrant:
    resource: str
    action: str

    @property
    def key(self) -> str:
        return f"{self.resource}:{self.action}"


class AuthorizationService:
    def __init__(self, session: Session, policy_evaluator: PolicyEvaluator | None = None) -> None:
        self.session = session
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()

    def resolve_permissions(
        self,
        *,
        principal_id: str | None,
        organization_id: UUID | None = None,
        principal_type: str = "user",
        scope_type: AuthorizationScope = "organization",
        scope_id: str | None = None,
    ) -> frozenset[str]:
        return self.resolve_permissions_for_scope(
            principal_id=principal_id,
            principal_type=principal_type,
            resource_scope=ResourceScope.from_values(
                scope_type=scope_type,
                organization_id=organization_id,
                resource_id=scope_id,
            ),
        )

    def resolve_permissions_for_scope(
        self,
        *,
        principal_id: str | None,
        resource_scope: ResourceScope,
        principal_type: str = "user",
        allowed_role_ids: frozenset[UUID] | None = None,
    ) -> frozenset[str]:
        if not principal_id:
            return frozenset()

        assigned_permissions = self._resolve_role_assignment_permissions(
            principal_id=principal_id,
            principal_type=principal_type,
            resource_scope=resource_scope,
            allowed_role_ids=allowed_role_ids,
        )
        policy_result = self.policy_evaluator.evaluate(
            policies=self._candidate_policies(resource_scope),
            resource_scope=resource_scope,
            principal_type=principal_type,
            principal_id=principal_id,
            assigned_permissions=assigned_permissions,
        )
        return frozenset((assigned_permissions | policy_result.granted_permissions) - policy_result.denied_permissions)

    def _resolve_role_assignment_permissions(
        self,
        *,
        principal_id: str,
        principal_type: str,
        resource_scope: ResourceScope,
        allowed_role_ids: frozenset[UUID] | None = None,
    ) -> frozenset[str]:
        if resource_scope.scope_type is ResourceScopeType.PLATFORM:
            scope_predicates = (
                RoleAssignment.organization_id.is_(None),
                *platform_role_criteria(),
                RoleAssignment.scope_type == "platform",
                or_(RoleAssignment.scope_id.is_(None), RoleAssignment.scope_id == resource_scope.scope_id),
            )
        elif resource_scope.scope_type is ResourceScopeType.ORGANIZATION:
            assert resource_scope.organization_id is not None
            organization_id = resource_scope.organization_id
            scope_predicates = (
                or_(RoleAssignment.organization_id == organization_id, RoleAssignment.organization_id.is_(None)),
                or_(Role.organization_id == organization_id, Role.organization_id.is_(None)),
                or_(
                    RoleAssignment.scope_type.is_(None),
                    RoleAssignment.scope_type == "organization",
                    and_(
                        RoleAssignment.organization_id.is_(None),
                        Role.organization_id.is_(None),
                        RoleAssignment.scope_type == "platform",
                    ),
                ),
                or_(
                    RoleAssignment.scope_id.is_(None),
                    RoleAssignment.scope_id == resource_scope.scope_id,
                    and_(
                        RoleAssignment.organization_id.is_(None),
                        Role.organization_id.is_(None),
                        RoleAssignment.scope_type == "platform",
                        RoleAssignment.scope_id == "platform",
                    ),
                ),
            )
        elif resource_scope.scope_type is ResourceScopeType.WORKLOAD:
            assert resource_scope.organization_id is not None
            organization_id = resource_scope.organization_id
            scope_predicates = (
                or_(RoleAssignment.organization_id == organization_id, RoleAssignment.organization_id.is_(None)),
                or_(Role.organization_id == organization_id, Role.organization_id.is_(None)),
                or_(RoleAssignment.scope_type.is_(None), RoleAssignment.scope_type.in_(("organization", "workload"))),
                or_(
                    RoleAssignment.scope_id.is_(None),
                    RoleAssignment.scope_id.in_((str(organization_id), resource_scope.scope_id)),
                ),
            )
        else:
            raise ValueError(f"unsupported authorization scope: {resource_scope.scope_type.value}")

        statement = (
            select(Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(
                RoleAssignment.principal_id == principal_id,
                RoleAssignment.principal_type == principal_type,
                RoleAssignment.status == "active",
                Role.status == "active",
                *scope_predicates,
            )
            .distinct()
        )
        if allowed_role_ids is not None:
            if not allowed_role_ids:
                return frozenset()
            statement = statement.where(RoleAssignment.role_id.in_(allowed_role_ids))

        return frozenset(
            PermissionGrant(resource=resource, action=action).key
            for resource, action in self.session.execute(statement).all()
        )

    def _candidate_policies(self, resource_scope: ResourceScope) -> list[Policy]:
        if resource_scope.scope_type is ResourceScopeType.PLATFORM:
            organization_predicate = Policy.organization_id.is_(None)
        else:
            organization_predicate = or_(
                Policy.organization_id == resource_scope.organization_id,
                Policy.organization_id.is_(None),
            )

        statement = (
            select(Policy)
            .where(
                Policy.status == "active",
                organization_predicate,
            )
            .order_by(Policy.organization_id.asc().nullsfirst(), Policy.code.asc())
        )
        return list(self.session.scalars(statement).all())
