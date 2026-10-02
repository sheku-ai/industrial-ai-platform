from __future__ import annotations

import json
from contextlib import suppress
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.contracts import AuthenticatedPrincipal
from app.identity.db import get_identity_db
from app.identity.service import IdentityService
from app.security.api_policy import is_membership_discovery, required_permissions
from app.security.resource_scope import ResourceScope, ResourceScopeType
from app.security.tenant_session import authorize_session_organization
from app.services.authorization import AuthorizationService

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _session_token(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.auth_cookie_name)


def get_optional_authenticated_principal(
    request: Request,
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedPrincipal | None:
    try:
        return IdentityService(identity_db, settings).resolve_session(
            _session_token(request, settings),
            request=request,
        )
    except SQLAlchemyError as exc:
        identity_db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_service_unavailable",
        ) from exc


def get_authenticated_principal(
    principal: AuthenticatedPrincipal | None = Depends(get_optional_authenticated_principal),
) -> AuthenticatedPrincipal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return principal


def require_full_access_principal(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> AuthenticatedPrincipal:
    if principal.user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_change_required",
        )
    return principal


def require_csrf(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedPrincipal:
    submitted = request.headers.get(settings.auth_csrf_header_name)
    if not IdentityService(identity_db, settings).validate_csrf(principal, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="csrf_validation_failed",
        )
    return principal


def _uuid_values(value) -> set[UUID]:
    result: set[UUID] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "organization_id" and item not in {None, ""}:
                try:
                    result.add(UUID(str(item)))
                except ValueError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="invalid_organization_id",
                    ) from exc
            else:
                result.update(_uuid_values(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_uuid_values(item))
    return result


async def _requested_organizations(request: Request) -> set[UUID]:
    values: set[UUID] = set()
    for candidate in (
        request.headers.get("X-Organization-ID"),
        request.query_params.get("organization_id"),
        request.path_params.get("organization_id"),
    ):
        if candidate:
            try:
                values.add(UUID(str(candidate)))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid_organization_id",
                ) from exc
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        body = await request.body()
        if body:
            with suppress(json.JSONDecodeError):
                values.update(_uuid_values(json.loads(body)))
    return values


async def require_api_access(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
    platform_db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    if principal.user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_change_required",
        )
    if request.method not in SAFE_METHODS:
        submitted = request.headers.get(settings.auth_csrf_header_name)
        if not IdentityService(identity_db, settings).validate_csrf(principal, submitted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="csrf_validation_failed",
            )
    try:
        scope_type = ResourceScopeType(
            request.headers.get("X-Authorization-Scope", "organization").strip().lower()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_authorization_scope",
        ) from exc
    if scope_type is ResourceScopeType.WORKLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_authorization_scope",
        )

    requested_organizations = await _requested_organizations(request)
    if is_membership_discovery(request.url.path, request.method):
        if requested_organizations - principal.organization_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization_membership_required",
            )
        request.state.authorized_runtime_context = {
            "scope_type": ResourceScopeType.PLATFORM.value,
            "organization_id": None,
            "actor_reference": principal.actor_reference,
            "permissions": frozenset(),
        }
        authorize_session_organization(platform_db, None)
        return principal

    selected_organization: UUID | None = None
    if scope_type is ResourceScopeType.ORGANIZATION:
        header_value = request.headers.get("X-Organization-ID")
        if header_value:
            selected_organization = UUID(header_value)
        elif len(requested_organizations) == 1:
            selected_organization = next(iter(requested_organizations))
        elif len(principal.organization_ids) == 1:
            selected_organization = next(iter(principal.organization_ids))
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_context_required",
            )
        if selected_organization not in principal.organization_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization_membership_required",
            )
        if requested_organizations - {selected_organization}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization_membership_required",
            )
        resource_scope = ResourceScope.organization(selected_organization)
        # The active membership is the organization access gate. Effective
        # authorization is then resolved from every persisted organization role
        # assignment, not only from the membership's bootstrap role.
        allowed_role_ids = None
    else:
        resource_scope = ResourceScope.platform()
        # Platform authority is represented by persisted platform-scoped role
        # assignments. Organization memberships are deliberately not a gate or
        # carrier for global authority.
        allowed_role_ids = None

    permissions = AuthorizationService(platform_db).resolve_permissions_for_scope(
        resource_scope=resource_scope,
        principal_id=principal.actor_reference,
        principal_type="user",
        allowed_role_ids=allowed_role_ids,
    )
    required = required_permissions(request.url.path, request.method)
    if scope_type is ResourceScopeType.PLATFORM and requested_organizations - principal.organization_ids:
        platform_required = frozenset(
            permission for permission in required if permission.startswith("platform.")
        )
        if not platform_required or permissions.isdisjoint(platform_required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization_membership_required",
            )
    if not required or permissions.isdisjoint(required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="permission_required",
        )
    request.state.authorized_runtime_context = {
        "scope_type": resource_scope.scope_type.value,
        "organization_id": resource_scope.organization_id,
        "actor_reference": principal.actor_reference,
        "permissions": permissions,
    }
    authorize_session_organization(platform_db, resource_scope.organization_id)
    return principal
