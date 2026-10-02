from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai import KnowledgeSource
from app.models.documents import Chunk, Collection, DocumentRecord, DocumentVersion
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument


def _collection_to_dict(collection: Collection) -> dict[str, Any]:
    return {
        "id": collection.id,
        "organization_id": collection.organization_id,
        "code": collection.code,
        "name": collection.name,
        "description": collection.description,
        "vector_provider": collection.vector_provider,
        "vector_collection_name": collection.vector_collection_name,
        "config": collection.config or {},
        "status": collection.status,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
        "created_by": collection.created_by,
        "updated_by": collection.updated_by,
    }


def _issue(code: str, message: str, *, component: str = "knowledge_collection_management") -> dict[str, Any]:
    return {"code": code, "message": message, "component": component}


def _organization_filter(organization_id: uuid.UUID | None):
    if organization_id is None:
        return Collection.organization_id.is_(None)
    return or_(Collection.organization_id.is_(None), Collection.organization_id == organization_id)


def list_knowledge_collections(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(Collection)
    if organization_id is not None:
        statement = statement.where(_organization_filter(organization_id))
    statement = statement.order_by(
        Collection.organization_id.asc().nullsfirst(), Collection.code.asc(), Collection.id.asc()
    )
    return [_collection_to_dict(item) for item in db.scalars(statement.offset(skip).limit(limit)).all()]


def get_knowledge_collection(db: Session, collection_id: uuid.UUID) -> dict[str, Any] | None:
    collection = db.get(Collection, collection_id)
    return _collection_to_dict(collection) if collection is not None else None


def get_collection_record(db: Session, collection_id: uuid.UUID) -> Collection | None:
    return db.get(Collection, collection_id)


def create_knowledge_collection(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    collection = Collection(**data)
    db.add(collection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(collection)
    return _collection_to_dict(collection)


def update_knowledge_collection(db: Session, collection: Collection, data: dict[str, Any]) -> dict[str, Any]:
    clean_data = {key: value for key, value in data.items() if value is not None}
    for key, value in clean_data.items():
        setattr(collection, key, value)
    db.add(collection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(collection)
    return _collection_to_dict(collection)


def activate_knowledge_collection(db: Session, collection: Collection) -> dict[str, Any]:
    return update_knowledge_collection(db, collection, {"status": "active"})


def deactivate_knowledge_collection(db: Session, collection: Collection) -> dict[str, Any]:
    return update_knowledge_collection(db, collection, {"status": "inactive"})


def _count_scalar(db: Session, statement: Any) -> int:
    value = db.scalar(statement)
    return int(value or 0)


def _record_ids(db: Session, collection_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(DocumentRecord.id)
            .where(DocumentRecord.collection_id == collection_id)
            .order_by(DocumentRecord.created_at.asc(), DocumentRecord.id.asc())
        ).all()
    )


def _knowledge_document_ids(db: Session, record_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if not record_ids:
        return []
    record_id_strings = [str(item) for item in record_ids]
    return list(
        db.scalars(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.status == "indexed",
                KnowledgeDocument.document_record_id.in_(record_id_strings),
            )
        ).all()
    )


def _knowledge_index_count(db: Session, knowledge_document_ids: list[uuid.UUID]) -> int:
    if not knowledge_document_ids:
        return 0
    return _count_scalar(
        db,
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.status == "indexed",
            KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),
        ),
    )


def _knowledge_chunk_count(db: Session, knowledge_document_ids: list[uuid.UUID]) -> int:
    if not knowledge_document_ids:
        return 0
    return _count_scalar(
        db,
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),
        ),
    )


def build_knowledge_collection_readiness(db: Session, collection: Collection) -> dict[str, Any]:
    record_ids = _record_ids(db, collection.id)
    knowledge_document_ids = _knowledge_document_ids(db, record_ids)
    document_count = len(record_ids)
    document_version_count = 0
    if record_ids:
        document_version_count = _count_scalar(
            db,
            select(func.count(DocumentVersion.id)).where(DocumentVersion.document_record_id.in_(record_ids)),
        )
    source_chunk_count = _count_scalar(db, select(func.count(Chunk.id)).where(Chunk.collection_id == collection.id))
    indexed_source_chunk_count = _count_scalar(
        db,
        select(func.count(Chunk.id)).where(Chunk.collection_id == collection.id, Chunk.status == "indexed"),
    )
    knowledge_chunk_count = _knowledge_chunk_count(db, knowledge_document_ids)
    knowledge_index_count = _knowledge_index_count(db, knowledge_document_ids)

    active = collection.status == "active"
    has_documents = document_count > 0
    has_chunks = knowledge_chunk_count > 0
    has_indexed_knowledge = knowledge_index_count > 0
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    if not active:
        blocking_issues.append(_issue("collection_inactive", "Knowledge collection is not active."))
    if not has_documents:
        warnings.append(_issue("collection_has_no_documents", "Knowledge collection has no associated documents."))
    if has_documents and not has_chunks:
        warnings.append(
            _issue("collection_has_no_knowledge_chunks", "Knowledge collection has documents but no knowledge chunks.")
        )
    if has_chunks and not has_indexed_knowledge:
        warnings.append(
            _issue("collection_has_no_indexed_knowledge", "Knowledge collection has chunks but no indexed knowledge.")
        )

    enterprise_search_ready = active and has_indexed_knowledge
    assistant_ready = enterprise_search_ready
    return {
        "collection_id": collection.id,
        "organization_id": collection.organization_id,
        "status": collection.status,
        "active": active,
        "document_count": document_count,
        "document_version_count": document_version_count,
        "chunk_count": knowledge_chunk_count,
        "indexed_chunk_count": knowledge_index_count,
        "source_chunk_count": source_chunk_count,
        "indexed_source_chunk_count": indexed_source_chunk_count,
        "knowledge_chunk_count": knowledge_chunk_count,
        "knowledge_index_count": knowledge_index_count,
        "has_documents": has_documents,
        "has_chunks": has_chunks,
        "has_indexed_knowledge": has_indexed_knowledge,
        "enterprise_search_ready": enterprise_search_ready,
        "assistant_ready": assistant_ready,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "semantic_search_required": False,
        "postgresql_source_of_truth": True,
    }


def build_knowledge_collection_contents(db: Session, collection: Collection) -> dict[str, Any]:
    readiness = build_knowledge_collection_readiness(db, collection)
    records = list(
        db.scalars(
            select(DocumentRecord)
            .where(DocumentRecord.collection_id == collection.id)
            .order_by(DocumentRecord.created_at.asc(), DocumentRecord.id.asc())
        ).all()
    )
    documents: list[dict[str, Any]] = []
    for record in records:
        version_count = _count_scalar(
            db,
            select(func.count(DocumentVersion.id)).where(DocumentVersion.document_record_id == record.id),
        )
        source_chunk_count = _count_scalar(
            db, select(func.count(Chunk.id)).where(Chunk.document_record_id == record.id)
        )
        indexed_documents = _knowledge_document_ids(db, [record.id])
        knowledge_chunk_count = _knowledge_chunk_count(db, indexed_documents)
        documents.append(
            {
                "document_record_id": record.id,
                "title": record.title,
                "status": record.status,
                "source_type": record.source_type,
                "version_count": version_count,
                "chunk_count": knowledge_chunk_count,
                "source_chunk_count": source_chunk_count,
                "knowledge_chunk_count": knowledge_chunk_count,
                "knowledge_index_count": _knowledge_index_count(db, indexed_documents),
            }
        )
    return {
        "collection": _collection_to_dict(collection),
        "documents": documents,
        "versions_count": readiness["document_version_count"],
        "chunks_count": readiness["knowledge_chunk_count"],
        "source_chunks_count": readiness["source_chunk_count"],
        "knowledge_index_count": readiness["knowledge_index_count"],
        "readiness": readiness,
    }


def prepare_knowledge_collection_source(
    db: Session,
    collection: Collection,
    *,
    source_type: str = "collection",
    config: dict[str, Any] | None = None,
    status: str = "active",
) -> dict[str, Any]:
    statement = select(KnowledgeSource).where(
        KnowledgeSource.collection_id == collection.id,
        KnowledgeSource.agent_id.is_(None),
        KnowledgeSource.source_type == source_type,
    )
    if collection.organization_id is None:
        statement = statement.where(KnowledgeSource.organization_id.is_(None))
    else:
        statement = statement.where(KnowledgeSource.organization_id == collection.organization_id)
    source = db.scalar(statement.order_by(KnowledgeSource.created_at.asc(), KnowledgeSource.id.asc()))
    descriptor = {
        "source_kind": "knowledge_collection",
        "collection_id": str(collection.id),
        "organization_id": str(collection.organization_id) if collection.organization_id else None,
        "code": collection.code,
        "name": collection.name,
        "status": collection.status,
        "retrieval_provider": "postgres_fts",
        "enterprise_search_supported": True,
        "assistant_runtime_binding_required": False,
        "postgresql_source_of_truth": True,
    }
    source_config = {
        **(config or {}),
        "descriptor": descriptor,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "semantic_search_required": False,
        "postgresql_source_of_truth": True,
    }
    if source is None:
        source = KnowledgeSource(
            organization_id=collection.organization_id,
            agent_id=None,
            collection_id=collection.id,
            source_type=source_type,
            source_id=str(collection.id),
            config=source_config,
            status=status,
        )
    else:
        source.source_id = str(collection.id)
        source.config = source_config
        source.status = status
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(source)
    return {
        "collection_id": collection.id,
        "organization_id": collection.organization_id,
        "source_prepared": True,
        "source_persisted": True,
        "knowledge_source_id": source.id,
        "source_type": source.source_type,
        "source_id": source.source_id or str(collection.id),
        "status": source.status,
        "descriptor": descriptor,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "semantic_search_required": False,
        "postgresql_source_of_truth": True,
    }
