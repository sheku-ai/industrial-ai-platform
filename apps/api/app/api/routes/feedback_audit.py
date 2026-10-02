import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.feedback_audit import (
    ExplorerItem,
    ExplorerListResponse,
    FeedbackAuditReadiness,
    FeedbackCreate,
    FeedbackRead,
)
from app.services.feedback_audit_ux import (
    build_feedback_audit_readiness,
    create_feedback,
    get_conversation_history,
    list_assistant_history,
    list_audit_events,
    list_audit_history,
    list_conversations,
    list_document_lifecycle_history,
    list_feedback,
    list_runtime_executions,
    list_runtime_records,
    list_search_history,
)

router = APIRouter(prefix="/feedback-audit", tags=["feedback-audit"])


@router.get("/readiness", response_model=FeedbackAuditReadiness)
def readiness(db: Session = Depends(get_db)):
    return build_feedback_audit_readiness(db)


@router.post("/feedback", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
def submit_feedback(payload: FeedbackCreate, db: Session = Depends(get_db)):
    return create_feedback(db, payload)


@router.get("/feedback", response_model=list[FeedbackRead])
def read_feedback(
    organization_id: uuid.UUID | None = Query(default=None),
    target_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_feedback(db, organization_id=organization_id, target_type=target_type, limit=limit)


@router.get("/audit/events", response_model=ExplorerListResponse)
def audit_events(
    organization_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_audit_events(db, organization_id=organization_id, resource_type=resource_type, limit=limit)


@router.get("/audit/history", response_model=ExplorerListResponse)
def audit_history(
    organization_id: uuid.UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_audit_history(db, organization_id=organization_id, entity_type=entity_type, limit=limit)


@router.get("/runtime/records", response_model=ExplorerListResponse)
def runtime_records(
    runtime_domain: str | None = Query(default=None),
    execution_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_runtime_records(db, runtime_domain=runtime_domain, execution_id=execution_id, limit=limit)


@router.get("/runtime/executions", response_model=ExplorerListResponse)
def runtime_executions(
    organization_id: uuid.UUID | None = Query(default=None),
    execution_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_runtime_executions(db, organization_id=organization_id, execution_type=execution_type, limit=limit)


@router.get("/conversations", response_model=ExplorerListResponse)
def conversations(
    assistant_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_conversations(db, assistant_id=assistant_id, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ExplorerItem)
def conversation_detail(conversation_id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_conversation_history(db, conversation_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return result


@router.get("/assistants/history", response_model=ExplorerListResponse)
def assistants_history(
    assistant_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_assistant_history(db, assistant_id=assistant_id, limit=limit)


@router.get("/search/history", response_model=ExplorerListResponse)
def search_history(
    assistant_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_search_history(db, assistant_id=assistant_id, limit=limit)


@router.get("/documents/lifecycle-history", response_model=ExplorerListResponse)
def document_lifecycle_history(
    organization_id: uuid.UUID | None = Query(default=None),
    document_record_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_document_lifecycle_history(
        db,
        organization_id=organization_id,
        document_record_id=document_record_id,
        limit=limit,
    )
