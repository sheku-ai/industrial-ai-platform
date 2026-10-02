from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.core import Organization


async def get_readiness_runtime_context(
    request: Request,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeRequestContext:
    if not context.actor_reference:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    organization_id = context.organization_id
    requested_scope = request.query_params.get("scope") or context.scope_type
    query_organization_id = request.query_params.get("organization_id")
    if requested_scope == "organization" and query_organization_id:
        try:
            organization_id = UUID(query_organization_id)
        except ValueError:
            organization_id = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        if isinstance(body, dict) and body.get("scope") == "organization" and body.get("organization_id"):
            try:
                organization_id = UUID(str(body["organization_id"]))
            except ValueError:
                organization_id = None
    if organization_id is not None and db.get(Organization, organization_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization_not_found",
        )
    return context
