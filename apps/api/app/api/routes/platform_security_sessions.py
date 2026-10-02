import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.db import get_identity_db
from app.schemas.session_management import (
    SessionMutationRead,
    SessionPolicyRead,
    SessionPolicyUpdate,
    UserSessionsRead,
)
from app.services.session_management import SessionManagementError, SessionManagementService

router = APIRouter(prefix="/platform/security", tags=["platform-security-sessions"])


def _service(context: RuntimeRequestContext, identity_db: Session, db: Session, settings: Settings):
    if context.scope_type != "platform" or context.organization_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="platform_scope_required")
    if not context.has_permission("platform.security", "administer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission_required")
    if not context.actor_reference:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authenticated_actor_required")
    return SessionManagementService(
        identity_db,
        db,
        settings,
        actor_reference=context.actor_reference,
        correlation_id=context.correlation_id,
    )


def _execute(operation, identity_db: Session, db: Session):
    try:
        return operation()
    except SessionManagementError as exc:
        identity_db.rollback()
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/session-policy", response_model=SessionPolicyRead)
def session_policy(
    response: Response,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    response.headers["Cache-Control"] = "no-store"
    return _service(context, identity_db, db, settings).policy()


@router.put("/session-policy", response_model=SessionPolicyRead)
def update_session_policy(
    payload: SessionPolicyUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _service(context, identity_db, db, settings)
    values = payload.model_dump(exclude={"application_mode"})
    return _execute(lambda: service.update_policy(values, payload.application_mode), identity_db, db)


@router.get("/users/{user_id}/sessions", response_model=UserSessionsRead)
def user_sessions(
    user_id: uuid.UUID,
    response: Response,
    session_status: Literal["all", "active", "expired", "revoked"] = Query(default="all", alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    response.headers["Cache-Control"] = "no-store"
    service = _service(context, identity_db, db, settings)
    return _execute(
        lambda: service.sessions(user_id, status_filter=session_status, offset=offset, limit=limit),
        identity_db,
        db,
    )


@router.delete("/users/{user_id}/sessions/{session_id}", response_model=SessionMutationRead)
def revoke_user_session(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _service(context, identity_db, db, settings)
    return _execute(lambda: service.revoke(user_id, session_id), identity_db, db)


@router.post("/users/{user_id}/sessions/revoke-all", response_model=SessionMutationRead)
def revoke_all_user_sessions(
    user_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _service(context, identity_db, db, settings)
    return _execute(lambda: service.revoke_all(user_id), identity_db, db)
