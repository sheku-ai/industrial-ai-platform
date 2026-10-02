import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.models.documents import DocumentRecord, DocumentVersion, IngestionJob
from app.schemas.document_review import (
    DocumentReviewCreate,
    DocumentReviewDecisionRequest,
    DocumentReviewEventRead,
    DocumentReviewRead,
)
from app.services.protected_document_review import (
    DocumentReviewAction,
    DocumentReviewReason,
    DocumentReviewStatus,
    InvalidReviewTransition,
    default_actions,
    validate_transition,
)

router = APIRouter(prefix="/document-reviews", tags=["document-reviews"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document review case not found")


@router.get("", response_model=list[DocumentReviewRead])
def list_document_reviews(
    organization_id: uuid.UUID | None = None,
    review_status: str | None = Query(default=None, alias="status"),
    skip: int = 0,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = select(DocumentReviewCase).order_by(DocumentReviewCase.created_at.desc()).offset(skip).limit(limit)
    if organization_id is not None:
        statement = statement.where(DocumentReviewCase.organization_id == organization_id)
    if review_status is not None:
        statement = statement.where(DocumentReviewCase.status == review_status)
    return list(db.scalars(statement).all())


@router.post("", response_model=DocumentReviewRead, status_code=status.HTTP_201_CREATED)
def create_document_review(payload: DocumentReviewCreate, db: Session = Depends(get_db)):
    document = db.get(DocumentRecord, payload.document_record_id)
    version = db.get(DocumentVersion, payload.document_version_id)
    if document is None or version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document or document version not found")
    if document.organization_id != payload.organization_id or version.organization_id != payload.organization_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document resources do not belong to organization"
        )
    if version.document_record_id != document.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document version does not belong to document")
    if payload.ingestion_job_id is not None:
        job = db.get(IngestionJob, payload.ingestion_job_id)
        if job is None or job.organization_id != payload.organization_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="ingestion job is invalid for organization"
            )

    try:
        reason = DocumentReviewReason(payload.reason)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported review reason"
        ) from exc

    allowed_actions = payload.allowed_actions or [action.value for action in default_actions(reason)]
    item = DocumentReviewCase(
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        ingestion_job_id=payload.ingestion_job_id,
        status=DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
        reason=reason.value,
        detected_format=payload.detected_format,
        detected_by=payload.detected_by,
        encryption_type=payload.encryption_type,
        allowed_actions=allowed_actions,
        metadata_json=payload.metadata,
        expires_at=payload.expires_at,
    )
    db.add(item)
    db.flush()
    db.add(
        DocumentReviewEvent(
            organization_id=item.organization_id,
            review_case_id=item.id,
            event_type="review_created",
            from_status=None,
            to_status=item.status,
            actor_subject=None,
            details={"reason": item.reason, "detected_by": item.detected_by},
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/{review_id}", response_model=DocumentReviewRead)
def get_document_review(review_id: uuid.UUID, db: Session = Depends(get_db)):
    item = db.get(DocumentReviewCase, review_id)
    if item is None:
        raise _not_found()
    return item


@router.get("/{review_id}/events", response_model=list[DocumentReviewEventRead])
def list_document_review_events(review_id: uuid.UUID, db: Session = Depends(get_db)):
    item = db.get(DocumentReviewCase, review_id)
    if item is None:
        raise _not_found()
    statement = (
        select(DocumentReviewEvent)
        .where(DocumentReviewEvent.review_case_id == review_id)
        .order_by(DocumentReviewEvent.created_at.asc())
    )
    return list(db.scalars(statement).all())


@router.post("/{review_id}/decisions", response_model=DocumentReviewRead)
def decide_document_review(
    review_id: uuid.UUID,
    payload: DocumentReviewDecisionRequest,
    db: Session = Depends(get_db),
):
    item = db.get(DocumentReviewCase, review_id)
    if item is None:
        raise _not_found()
    try:
        action = DocumentReviewAction(payload.action)
        current = DocumentReviewStatus(item.status)
        target = DocumentReviewStatus(payload.target_status)
        validate_transition(current, target)
    except (ValueError, InvalidReviewTransition) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if action.value not in item.allowed_actions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="action is not allowed for this review")
    if action == DocumentReviewAction.PROVIDE_PASSWORD:
        if payload.secret_reference is None or payload.secret_expires_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="temporary secret reference and expiry are required",
            )
        if payload.secret_expires_at <= datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="temporary secret must expire in the future"
            )
        item.secret_reference = payload.secret_reference
        item.secret_expires_at = payload.secret_expires_at
        item.secret_single_use = payload.secret_single_use
    else:
        if payload.secret_reference is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="secret reference is only valid for provide_password",
            )

    previous_status = item.status
    item.status = target.value
    item.updated_by = payload.reviewer_subject
    if target in {
        DocumentReviewStatus.RESOLVED,
        DocumentReviewStatus.REJECTED_BY_REVIEWER,
        DocumentReviewStatus.QUARANTINED,
        DocumentReviewStatus.EXPIRED,
    }:
        item.resolved_at = datetime.now(UTC)

    db.add(
        DocumentReviewEvent(
            organization_id=item.organization_id,
            review_case_id=item.id,
            event_type="review_decision",
            from_status=previous_status,
            to_status=item.status,
            action=action.value,
            actor_subject=payload.reviewer_subject,
            note=payload.note,
            details={
                "secret_reference_supplied": payload.secret_reference is not None,
                "secret_single_use": payload.secret_single_use if payload.secret_reference else None,
            },
        )
    )
    db.commit()
    db.refresh(item)
    return item
