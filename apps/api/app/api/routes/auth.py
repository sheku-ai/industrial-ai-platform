from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import (
    get_authenticated_principal,
    get_optional_authenticated_principal,
    require_csrf,
)
from app.core.config import Settings, get_settings
from app.identity.contracts import AuthenticatedPrincipal
from app.identity.db import get_identity_db
from app.identity.passwords import PasswordPolicyError
from app.identity.service import IdentityService
from app.schemas.auth import (
    AuthMeResponse,
    AuthUserRead,
    ChangePasswordRequest,
    CsrfTokenResponse,
    LoginRequest,
    LoginResponse,
    MembershipRead,
    PasswordChangedResponse,
    SessionPageRead,
    SessionPolicyPublicRead,
    SessionRead,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _response_payload(principal: AuthenticatedPrincipal) -> dict:
    return {
        "user": AuthUserRead(
            id=principal.user.id,
            username=principal.user.username,
            email=principal.user.email_display,
            display_name=principal.user.display_name,
            status=principal.user.status,
            must_change_password=principal.user.must_change_password,
        ),
        "session": SessionRead(
            id=principal.session.id,
            created_at=principal.session.created_at,
            last_activity_at=principal.session.last_activity_at,
            idle_expires_at=principal.session.idle_expires_at,
            absolute_expires_at=principal.session.absolute_expires_at,
            remember_me=principal.session.remember_me,
        ),
        "memberships": [MembershipRead.model_validate(item) for item in principal.memberships],
    }


def _set_session_cookie(
    response: Response,
    token: str,
    principal: AuthenticatedPrincipal,
    settings: Settings,
) -> None:
    cookie_options = {}
    if principal.session.remember_me:
        remaining = max(
            0,
            int((principal.session.absolute_expires_at - datetime.now(UTC)).total_seconds()),
        )
        cookie_options["max_age"] = remaining
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
        **cookie_options,
    )


def _expire_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    service = IdentityService(identity_db, settings)
    try:
        principal, token = service.authenticate(
            email=payload.email,
            password=payload.password,
            request=request,
            remember_me=payload.remember_me,
        )
    except ValueError as exc:
        if str(exc) == "login_rate_limited":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="invalid_email_or_password",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_email_or_password",
        ) from exc
    _set_session_cookie(response, token, principal, settings)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(**_response_payload(principal))


@router.get("/me", response_model=AuthMeResponse)
def me(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> AuthMeResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthMeResponse(**_response_payload(principal))


@router.get("/session-policy", response_model=SessionPolicyPublicRead)
def public_session_policy(
    response: Response,
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> SessionPolicyPublicRead:
    policy = IdentityService(identity_db, settings).session_policy()
    response.headers["Cache-Control"] = "no-store"
    return SessionPolicyPublicRead(remember_me_enabled=policy.remember_me_enabled)


@router.get("/sessions", response_model=SessionPageRead)
def own_sessions(
    response: Response,
    session_status: Literal["all", "active", "expired", "revoked"] = Query(default="all", alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
):
    response.headers["Cache-Control"] = "no-store"
    return IdentityService(identity_db, settings).list_sessions(
        principal.user.id,
        current_session_id=principal.session.id,
        status_filter=session_status,
        offset=offset,
        limit=limit,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_own_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    service = IdentityService(identity_db, settings)
    session_model = type(principal.session)
    target = identity_db.scalar(select(session_model).where(session_model.id == session_id).with_for_update())
    if target is None or target.user_id != principal.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    service.revoke_session(
        target,
        reason="self_revocation",
        request=request,
        user=principal.user,
        actor_reference=principal.actor_reference,
    )
    identity_db.commit()
    if target.id == principal.session.id:
        _expire_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
def revoke_other_sessions(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    service = IdentityService(identity_db, settings)
    service.revoke_user_sessions(
        principal.user,
        reason="self_revocation",
        request=request,
        exclude_session_id=principal.session.id,
        actor_reference=principal.actor_reference,
    )
    identity_db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/csrf", response_model=CsrfTokenResponse)
def csrf_token(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> CsrfTokenResponse:
    token = IdentityService(identity_db, settings).rotate_csrf_token(principal)
    response.headers["Cache-Control"] = "no-store"
    return CsrfTokenResponse(csrf_token=token, header_name=settings.auth_csrf_header_name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal | None = Depends(get_optional_authenticated_principal),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    service = IdentityService(identity_db, settings)
    if principal is not None and not service.validate_csrf(
        principal, request.headers.get(settings.auth_csrf_header_name)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="csrf_validation_failed",
        )
    service.logout(principal, request=request)
    _expire_session_cookie(response, settings)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", response_model=PasswordChangedResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> PasswordChangedResponse:
    service = IdentityService(identity_db, settings)
    try:
        service.change_password(
            principal,
            current_password=payload.current_password,
            new_password=payload.new_password,
            request=request,
        )
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current_password_is_incorrect",
        ) from exc
    _expire_session_cookie(response, settings)
    response.headers["Cache-Control"] = "no-store"
    return PasswordChangedResponse()
