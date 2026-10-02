from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_authenticated_principal
from app.db.session import get_db
from app.identity.contracts import AuthenticatedPrincipal
from app.security.resource_scope import ResourceScope, ResourceScopeType
from app.services.authorization import AuthorizationService


@dataclass(frozen=True)
class RuntimeRequestContext:
    scope_type: str
    organization_id: UUID | None
    actor_reference: str | None
    permissions: frozenset[str]
    correlation_id: str = ""

    @property
    def resource_scope(self) -> ResourceScope:
        return ResourceScope.from_values(
            scope_type=self.scope_type,
            organization_id=self.organization_id,
        )

    @property
    def scope_id(self) -> str:
        return self.resource_scope.scope_id

    def has_permission(self, resource: str, action: str) -> bool:
        return f"{resource}:{action}" in self.permissions

    def is_scope(self, scope_type: ResourceScopeType | str) -> bool:
        return self.resource_scope.is_type(scope_type)


def get_runtime_context(
    request: Request,
    x_authorization_scope: str = Header(default="organization", alias="X-Authorization-Scope"),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> RuntimeRequestContext:
    authorized = getattr(request.state, "authorized_runtime_context", None)
    if isinstance(authorized, dict):
        return RuntimeRequestContext(
            scope_type=authorized["scope_type"],
            organization_id=authorized["organization_id"],
            actor_reference=authorized["actor_reference"],
            permissions=frozenset(authorized["permissions"]),
            correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
        )

    try:
        requested_scope = ResourceScopeType(x_authorization_scope.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid authorization scope",
        ) from exc

    if requested_scope is ResourceScopeType.WORKLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workload scope is a resource scope and cannot be used as a request authorization scope",
        )

    try:
        resource_scope = ResourceScope.from_values(
            scope_type=requested_scope,
            organization_id=x_organization_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_authorization_scope_context",
        ) from exc

    if (
        resource_scope.scope_type is ResourceScopeType.ORGANIZATION
        and resource_scope.organization_id not in principal.organization_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization_membership_required",
        )

    permissions = AuthorizationService(db).resolve_permissions_for_scope(
        resource_scope=resource_scope,
        principal_id=principal.actor_reference,
        principal_type="user",
        # Both organization and platform authority are resolved from their
        # persisted, scope-specific assignments. Membership remains the
        # organization boundary check above; it must not carry global roles.
        allowed_role_ids=None,
    )

    return RuntimeRequestContext(
        scope_type=resource_scope.scope_type.value,
        organization_id=resource_scope.organization_id,
        actor_reference=principal.actor_reference,
        permissions=permissions,
        correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
    )
