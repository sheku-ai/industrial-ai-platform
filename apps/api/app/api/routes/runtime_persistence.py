from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.runtime_persistence_runtime import read_runtime_persistence

router = APIRouter(prefix="/runtime/persistence", tags=["runtime-persistence"])


@router.get("/{execution_id}")
def get_runtime_persistence(
    execution_id: str,
    db: Session = Depends(get_db),
):
    result = read_runtime_persistence(db, execution_id=execution_id)
    if result.get("record_count") == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="runtime persistence execution not found")
    return result
