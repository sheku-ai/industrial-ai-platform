import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.documents import StorageExecutionRequestPayload
from app.services.storage_execution_control_plane import (
    build_storage_execution_prepare,
    build_storage_execution_request_status,
    build_storage_execution_status,
)

router = APIRouter(prefix="/storage/execution", tags=["storage-execution"])


@router.get("/{artifact_id}/status")
def get_storage_execution_status(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_storage_execution_status(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result


@router.post("/{artifact_id}/prepare")
def prepare_storage_execution(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_storage_execution_prepare(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result


@router.post("/{artifact_id}/request")
def request_storage_execution(
    artifact_id: uuid.UUID,
    payload: StorageExecutionRequestPayload,
    db: Session = Depends(get_db),
):
    result = build_storage_execution_request_status(
        db,
        artifact_id=artifact_id,
        requested_operation=payload.requested_operation,
        requested_by=payload.requested_by,
        request_metadata=payload.request_metadata,
        idempotency_key=payload.idempotency_key,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result
