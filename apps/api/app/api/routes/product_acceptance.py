from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.models.core import Organization
from app.schemas.product_acceptance import (
    AcceptanceExecutionCreate,
    AcceptanceExecutionListResponse,
    AcceptanceExecutionRead,
    AcceptanceExecutionUpdate,
    AcceptanceGateRead,
    AcceptanceGateUpsert,
    AcceptanceResourceRead,
    AcceptanceResourceUpsert,
)
from app.services.product_acceptance.conversation_runtime_evidence import (
    build_assistant_conversation_runtime_evidence,
)
from app.services.product_acceptance.runtime_evidence import (
    build_document_runtime_evidence,
    build_enterprise_search_runtime_evidence,
)
from app.services.product_acceptance_evidence import (
    create_or_get_acceptance_execution,
    get_acceptance_execution,
    list_acceptance_executions,
    update_acceptance_execution,
    upsert_acceptance_gate,
    upsert_acceptance_resource,
)

router = APIRouter(prefix="/product-acceptance", tags=["product-acceptance"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="acceptance execution not found")


def _require(context: RuntimeRequestContext, db: Session, *, platform_action: str) -> None:
    if context.actor_reference is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    if (
        context.is_scope("organization")
        and context.organization_id is not None
        and db.get(Organization, context.organization_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )
    if not (
        context.has_permission("product_acceptance", "execute")
        or (context.is_scope("platform") and context.has_permission("platform.production_acceptance", platform_action))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="product acceptance permission is required",
        )


def _visible(result: dict, context: RuntimeRequestContext) -> bool:
    return context.is_scope("platform") or (
        context.organization_id is not None and result.get("organization_id") == context.organization_id
    )


@router.get("/contract", include_in_schema=False)
def read_acceptance_contract(
    request: Request,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    """Return the authenticated API contract without exposing public API documentation."""
    _require(context, db, platform_action="read")
    return request.app.openapi()


@router.get("/runtime-evidence/document-lifecycle", include_in_schema=False)
def read_document_runtime_evidence(
    artifact_id: uuid.UUID = Query(...),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    """Return organization-scoped authoritative evidence used by Product Acceptance."""
    _require(context, db, platform_action="read")
    if not context.is_scope("organization") or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization scope is required",
        )
    return build_document_runtime_evidence(
        db,
        organization_id=context.organization_id,
        artifact_id=artifact_id,
    )


@router.get("/runtime-evidence/enterprise-search", include_in_schema=False)
def read_enterprise_search_runtime_evidence(
    evidence_id: uuid.UUID = Query(...),
    expected_query: str = Query(..., min_length=1),
    expected_artifact_id: str = Query(..., min_length=1),
    expected_knowledge_document_id: str = Query(..., min_length=1),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    """Verify exact persisted Enterprise Search evidence for Product Acceptance."""
    _require(context, db, platform_action="read")
    if not context.is_scope("organization") or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization scope is required",
        )
    return build_enterprise_search_runtime_evidence(
        db,
        organization_id=context.organization_id,
        evidence_id=evidence_id,
        expected_query=expected_query,
        expected_artifact_id=expected_artifact_id,
        expected_knowledge_document_id=expected_knowledge_document_id,
    )


@router.get("/runtime-evidence/assistant-conversation", include_in_schema=False)
def read_assistant_conversation_runtime_evidence(
    conversation_id: uuid.UUID = Query(...),
    assistant_run_id: uuid.UUID = Query(...),
    expected_assistant_id: uuid.UUID = Query(...),
    expected_assistant_response_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    """Verify persisted Assistant Execution -> Conversation Event lineage for Product Acceptance."""
    _require(context, db, platform_action="read")
    if not context.is_scope("organization") or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization scope is required",
        )
    return build_assistant_conversation_runtime_evidence(
        db,
        organization_id=context.organization_id,
        conversation_id=conversation_id,
        assistant_run_id=assistant_run_id,
        expected_assistant_id=expected_assistant_id,
        expected_assistant_response_id=expected_assistant_response_id,
    )


@router.get("/executions", response_model=AcceptanceExecutionListResponse)
def list_executions(
    scenario: str | None = Query(default=None),
    execution_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="read")
    executions = list_acceptance_executions(db, scenario=scenario, status=execution_status, limit=limit)
    executions = [item for item in executions if _visible(item, context)]
    return {"executions": executions, "count": len(executions), "postgresql_source_of_truth": True}


@router.post("/executions", response_model=AcceptanceExecutionRead, status_code=status.HTTP_201_CREATED)
def create_execution(
    payload: AcceptanceExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="administer")
    if not context.is_scope("platform") and payload.organization_id != context.organization_id:
        raise _not_found()
    try:
        return create_or_get_acceptance_execution(db, payload)
    except ValueError as exc:
        raise runtime_http_error(exc) from exc


@router.get("/executions/{execution_key}", response_model=AcceptanceExecutionRead)
def read_execution(
    execution_key: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="read")
    result = get_acceptance_execution(db, execution_key)
    if result is None or not _visible(result, context):
        raise _not_found()
    return result


@router.patch("/executions/{execution_key}", response_model=AcceptanceExecutionRead)
def update_execution(
    execution_key: str,
    payload: AcceptanceExecutionUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="administer")
    current = get_acceptance_execution(db, execution_key)
    if current is None or not _visible(current, context):
        raise _not_found()
    if (
        payload.organization_id is not None
        and not context.is_scope("platform")
        and payload.organization_id != context.organization_id
    ):
        raise _not_found()
    result = update_acceptance_execution(db, execution_key, payload)
    if result is None:
        raise _not_found()
    return result


@router.post("/executions/{execution_key}/gates", response_model=AcceptanceGateRead)
def upsert_gate(
    execution_key: str,
    payload: AcceptanceGateUpsert,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="administer")
    current = get_acceptance_execution(db, execution_key)
    if current is None or not _visible(current, context):
        raise _not_found()
    result = upsert_acceptance_gate(db, execution_key, payload)
    if result is None:
        raise _not_found()
    return result


@router.post("/executions/{execution_key}/resources", response_model=AcceptanceResourceRead)
def upsert_resource(
    execution_key: str,
    payload: AcceptanceResourceUpsert,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, db, platform_action="administer")
    current = get_acceptance_execution(db, execution_key)
    if current is None or not _visible(current, context):
        raise _not_found()
    result = upsert_acceptance_resource(db, execution_key, payload)
    if result is None:
        raise _not_found()
    return result
