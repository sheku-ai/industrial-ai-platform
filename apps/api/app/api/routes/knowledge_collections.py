import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.knowledge_collections import (
    KnowledgeCollectionContents,
    KnowledgeCollectionCreate,
    KnowledgeCollectionKnowledgeSourceRequest,
    KnowledgeCollectionKnowledgeSourceResponse,
    KnowledgeCollectionRead,
    KnowledgeCollectionReadiness,
    KnowledgeCollectionUpdate,
)
from app.services.knowledge_collection_management import (
    activate_knowledge_collection,
    build_knowledge_collection_contents,
    build_knowledge_collection_readiness,
    create_knowledge_collection,
    deactivate_knowledge_collection,
    get_collection_record,
    get_knowledge_collection,
    list_knowledge_collections,
    prepare_knowledge_collection_source,
    update_knowledge_collection,
)

router = APIRouter(prefix="/knowledge/collections", tags=["knowledge-collections"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge collection not found")


def _conflict(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "knowledge_collection_conflict",
            "details": str(getattr(exc, "orig", exc)),
        },
    )


@router.get("", response_model=list[KnowledgeCollectionRead])
def list_collections(
    organization_id: uuid.UUID | None = Query(default=None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_knowledge_collections(db, organization_id=organization_id, skip=skip, limit=limit)


@router.post("", response_model=KnowledgeCollectionRead, status_code=status.HTTP_201_CREATED)
def create_collection(payload: KnowledgeCollectionCreate, db: Session = Depends(get_db)):
    try:
        return create_knowledge_collection(db, payload.model_dump())
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.get("/{collection_id}", response_model=KnowledgeCollectionRead)
def read_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_knowledge_collection(db, collection_id)
    if result is None:
        raise _not_found()
    return result


@router.patch("/{collection_id}", response_model=KnowledgeCollectionRead)
def update_collection(collection_id: uuid.UUID, payload: KnowledgeCollectionUpdate, db: Session = Depends(get_db)):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    try:
        return update_knowledge_collection(db, collection, payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.post("/{collection_id}/activate", response_model=KnowledgeCollectionRead)
def activate_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    return activate_knowledge_collection(db, collection)


@router.post("/{collection_id}/deactivate", response_model=KnowledgeCollectionRead)
def deactivate_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    return deactivate_knowledge_collection(db, collection)


@router.get("/{collection_id}/readiness", response_model=KnowledgeCollectionReadiness)
def read_collection_readiness(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    return build_knowledge_collection_readiness(db, collection)


@router.get("/{collection_id}/contents", response_model=KnowledgeCollectionContents)
def read_collection_contents(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    return build_knowledge_collection_contents(db, collection)


@router.post("/{collection_id}/knowledge-source", response_model=KnowledgeCollectionKnowledgeSourceResponse)
def prepare_collection_knowledge_source(
    collection_id: uuid.UUID,
    payload: KnowledgeCollectionKnowledgeSourceRequest | None = None,
    db: Session = Depends(get_db),
):
    collection = get_collection_record(db, collection_id)
    if collection is None:
        raise _not_found()
    payload = payload or KnowledgeCollectionKnowledgeSourceRequest()
    return prepare_knowledge_collection_source(
        db,
        collection,
        source_type=payload.source_type,
        config=payload.config,
        status=payload.status,
    )
