from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.documents import DocumentRegistrationRequest
from app.services.document_registration_execution import build_document_registration_execution

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/registration/execute", status_code=status.HTTP_201_CREATED)
def execute_document_registration(
    payload: DocumentRegistrationRequest,
    db: Session = Depends(get_db),
):
    try:
        result = build_document_registration_execution(db, payload=payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="document registration execution conflict",
        ) from exc

    if result.get("execution_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    return result
