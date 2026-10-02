from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.documents import DocumentVersionPlanRequest
from app.services.document_version_planning import build_document_version_plan

router = APIRouter(prefix="/documents", tags=["document-versions"])


@router.post("/versions/plan")
def plan_document_version(
    payload: DocumentVersionPlanRequest,
    db: Session = Depends(get_db),
):
    return build_document_version_plan(db, payload=payload)
