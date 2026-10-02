import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document_review import DocumentReviewCase
from app.services.document_review_runtime import DocumentReviewRuntimeError, DocumentReviewRuntimeService
from app.services.secret_store import SecretStore
from app.services.secret_store_runtime import get_secret_store

router = APIRouter(prefix="/document-reviews", tags=["document-reviews"])


class DocumentReviewCredentialRequest(BaseModel):
    credential: SecretStr
    actor_subject: str = Field(min_length=1, max_length=255)
    ttl_seconds: int = Field(default=300, ge=1, le=3600)


class DocumentReviewCredentialResponse(BaseModel):
    review_id: uuid.UUID
    status: str
    secret_expires_at: str
    secret_single_use: bool


class DocumentReviewRetryRequest(BaseModel):
    actor_subject: str = Field(min_length=1, max_length=255)


class DocumentReviewRetryResponse(BaseModel):
    review_id: uuid.UUID
    runtime_execution_id: uuid.UUID
    status: str


class DocumentReviewExpiryResponse(BaseModel):
    expired_count: int


@router.post("/expire-due", response_model=DocumentReviewExpiryResponse)
def expire_due_document_reviews(
    db: Session = Depends(get_db),
    secret_store: SecretStore = Depends(get_secret_store),
):
    count = DocumentReviewRuntimeService(secret_store).expire_due_cases(db)
    return DocumentReviewExpiryResponse(expired_count=count)


@router.post(
    "/{review_id}/credentials",
    response_model=DocumentReviewCredentialResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def supply_protected_document_credentials(
    review_id: uuid.UUID,
    payload: DocumentReviewCredentialRequest,
    db: Session = Depends(get_db),
    secret_store: SecretStore = Depends(get_secret_store),
):
    review_case = db.get(DocumentReviewCase, review_id)
    if review_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document review case not found")
    try:
        review_case = DocumentReviewRuntimeService(secret_store).supply_credentials(
            db,
            review_case=review_case,
            secret_value=payload.credential.get_secret_value(),
            actor_subject=payload.actor_subject,
            ttl_seconds=payload.ttl_seconds,
        )
    except DocumentReviewRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DocumentReviewCredentialResponse(
        review_id=review_case.id,
        status=review_case.status,
        secret_expires_at=review_case.secret_expires_at.isoformat(),
        secret_single_use=review_case.secret_single_use,
    )


@router.post("/{review_id}/retry", response_model=DocumentReviewRetryResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_protected_document(
    review_id: uuid.UUID,
    payload: DocumentReviewRetryRequest,
    db: Session = Depends(get_db),
    secret_store: SecretStore = Depends(get_secret_store),
):
    review_case = db.get(DocumentReviewCase, review_id)
    if review_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document review case not found")
    try:
        execution = DocumentReviewRuntimeService(secret_store).authorize_retry(
            db,
            review_case=review_case,
            actor_subject=payload.actor_subject,
        )
    except DocumentReviewRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DocumentReviewRetryResponse(
        review_id=review_case.id,
        runtime_execution_id=execution.id,
        status=execution.status,
    )
