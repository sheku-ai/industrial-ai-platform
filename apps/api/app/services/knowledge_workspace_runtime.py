from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai import KnowledgeSource
from app.models.documents import Chunk, Collection, DocumentRecord
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.services.knowledge_collection_management import build_knowledge_collection_readiness
from app.services.knowledge_fts_runtime import build_knowledge_fts_health
from app.services.knowledge_lifecycle_runtime import build_knowledge_index_health, build_knowledge_index_statistics
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime

KNOWLEDGE_WORKSPACE_RUNTIME_SCHEMA_VERSION = "1"
KNOWLEDGE_WORKSPACE_RUNTIME_NAME = "knowledge_workspace_runtime"
SAMPLE_CHUNK_LIMIT = 10
DOCUMENT_LIMIT = 100


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by(db: Session, model: Any, column: Any, *criteria: Any) -> dict[str, int]:
    statement = select(column, func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    rows = db.execute(statement.group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _as_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _readiness_status(ready: bool) -> str:
    return "ready" if ready else "pending"


def _is_validation_document(record: DocumentRecord) -> bool:
    source = record.source_ref or {}
    return bool(
        source.get("execution_key")
        or source.get("scenario") == "local_product_acceptance"
        or source.get("smoke")
        or source.get("provider") == "smoke"
    )


def _is_validation_config(config: dict[str, Any] | None) -> bool:
    values = config or {}
    external_ref = str(values.get("external_ref") or "")
    return bool(
        values.get("validation_generated") is True
        or values.get("smoke") is True
        or values.get("smoke_runtime")
        or values.get("execution_key")
        or external_ref.startswith("acceptance-collection-")
        or "local-product-acceptance-" in external_ref
    )


def _collection_knowledge_counts(db: Session, collection_id: uuid.UUID) -> tuple[int, int]:
    records = list(db.scalars(select(DocumentRecord).where(DocumentRecord.collection_id == collection_id)).all())
    record_ids = [record.id for record in records if not _is_validation_document(record)]
    if not record_ids:
        return 0, 0
    knowledge_documents = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.document_record_id.in_([str(record_id) for record_id in record_ids])
            )
        ).all()
    )
    knowledge_ids = [document.id for document in knowledge_documents]
    return len(knowledge_documents), _count(
        db, KnowledgeChunk, KnowledgeChunk.knowledge_document_id.in_(knowledge_ids)
    )


def _collections(db: Session, *, organization_id: uuid.UUID | None, platform_scope: bool) -> list[dict[str, Any]]:
    statement = select(Collection)
    if not platform_scope:
        statement = statement.where(Collection.organization_id == organization_id)
    records = list(db.scalars(statement.order_by(Collection.code.asc(), Collection.id.asc())).all())
    records = [collection for collection in records if not _is_validation_config(collection.config)]
    items: list[dict[str, Any]] = []
    for collection in records:
        readiness = build_knowledge_collection_readiness(db, collection)
        source_count = _count(db, KnowledgeSource, KnowledgeSource.collection_id == collection.id)
        document_count = len(
            [
                record
                for record in db.scalars(
                    select(DocumentRecord).where(DocumentRecord.collection_id == collection.id)
                ).all()
                if not _is_validation_document(record)
            ]
        )
        knowledge_document_count, chunk_count = _collection_knowledge_counts(db, collection.id)
        items.append(
            {
                "collection_id": collection.id,
                "organization_id": collection.organization_id,
                "code": collection.code,
                "name": collection.name,
                "status": collection.status,
                "document_count": document_count,
                "knowledge_document_count": knowledge_document_count,
                "chunk_count": chunk_count,
                "source_count": source_count,
                "readiness": {
                    "status": _readiness_status(bool(readiness.get("enterprise_search_ready"))),
                    "active": bool(readiness.get("active")),
                    "has_documents": bool(readiness.get("has_documents")),
                    "has_chunks": bool(readiness.get("has_chunks")),
                    "has_indexed_knowledge": bool(readiness.get("has_indexed_knowledge")),
                    "enterprise_search_ready": bool(readiness.get("enterprise_search_ready")),
                    "assistant_ready": bool(readiness.get("assistant_ready")),
                    "warnings": readiness.get("warnings") or [],
                    "blocking_issues": readiness.get("blocking_issues") or [],
                },
            }
        )
    return items


def _knowledge_sources(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> list[dict[str, Any]]:
    statement = select(KnowledgeSource)
    if not platform_scope:
        statement = statement.where(KnowledgeSource.organization_id == organization_id)
    records = list(
        db.scalars(statement.order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id.desc())).all()
    )
    records = [source for source in records if not _is_validation_config(source.config)]
    return [
        {
            "source_id": item.id,
            "collection_id": item.collection_id,
            "source_type": item.source_type,
            "source_status": item.status,
            "readiness": _readiness_status(item.status == "active" and item.collection_id is not None),
            "configured": item.collection_id is not None and item.source_type is not None,
        }
        for item in records
    ]


def _knowledge_document_title(db: Session, document_record_id: str | None) -> str | None:
    record_id = _as_uuid(document_record_id)
    if record_id is None:
        return None
    record = db.get(DocumentRecord, record_id)
    return record.title if record is not None else None


def _knowledge_document_collection_id(db: Session, document_record_id: str | None) -> uuid.UUID | None:
    record_id = _as_uuid(document_record_id)
    if record_id is None:
        return None
    record = db.get(DocumentRecord, record_id)
    return record.collection_id if record is not None else None


def _knowledge_documents(db: Session, *, record_ids: list[str], platform_scope: bool) -> list[dict[str, Any]]:
    statement = select(KnowledgeDocument)
    if not platform_scope:
        statement = statement.where(KnowledgeDocument.document_record_id.in_(record_ids))
    records = list(
        db.scalars(
            statement.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.created_at.desc())
            .limit(DOCUMENT_LIMIT)
        ).all()
    )
    items: list[dict[str, Any]] = []
    for item in records:
        chunk_count = _count(db, KnowledgeChunk, KnowledgeChunk.knowledge_document_id == item.id)
        indexed_chunks = _count(
            db,
            KnowledgeChunk,
            KnowledgeChunk.knowledge_document_id == item.id,
            KnowledgeChunk.status.in_(("indexed", "ready")),
        )
        collection_id = _knowledge_document_collection_id(db, item.document_record_id)
        items.append(
            {
                "knowledge_document_id": item.id,
                "document_record_id": item.document_record_id,
                "document_version_id": item.document_version_id,
                "artifact_id": item.artifact_id,
                "collection_id": collection_id,
                "title": _knowledge_document_title(db, item.document_record_id)
                or (item.metadata_json or {}).get("title")
                or item.artifact_id,
                "status": item.status,
                "chunk_count": chunk_count,
                "indexed_at": item.updated_at,
                "created_at": item.created_at,
                "readiness": {
                    "status": _readiness_status(item.status in {"indexed", "ready"} and indexed_chunks > 0),
                    "indexed_chunks": indexed_chunks,
                    "searchable": item.status in {"indexed", "ready"} and indexed_chunks > 0,
                },
            }
        )
    return items


def _chunk_overview(
    db: Session,
    index_statistics: dict[str, Any],
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
    knowledge_document_ids: list[uuid.UUID],
) -> dict[str, Any]:
    knowledge_criteria = (
        () if platform_scope else (KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),)
    )
    source_criteria = () if platform_scope else (Chunk.organization_id == organization_id,)
    total_chunks = _count(db, KnowledgeChunk, *knowledge_criteria)
    indexed_chunks = _count(
        db,
        KnowledgeChunk,
        *knowledge_criteria,
        KnowledgeChunk.status.in_(("indexed", "ready")),
    )
    source_chunks = _count(db, Chunk, *source_criteria)
    sample_statement = select(KnowledgeChunk)
    if knowledge_criteria:
        sample_statement = sample_statement.where(*knowledge_criteria)
    sample_records = list(
        db.scalars(
            sample_statement.order_by(KnowledgeChunk.created_at.desc(), KnowledgeChunk.id.desc())
            .limit(SAMPLE_CHUNK_LIMIT)
        ).all()
    )
    return {
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "source_chunks": source_chunks,
        "chunks_by_status": _count_by(db, KnowledgeChunk, KnowledgeChunk.status, *knowledge_criteria),
        "sample_chunks": [
            {
                "chunk_id": item.id,
                "knowledge_document_id": item.knowledge_document_id,
                "published_chunk_id": item.published_chunk_id,
                "status": item.status,
                "chunk_scope": item.chunk_scope,
                "text_preview": item.text[:240],
                "created_at": item.created_at,
            }
            for item in sample_records
        ],
        "chunk_diagnostics": {
            "source_chunks": source_chunks,
            "indexed_chunk_coverage": float(indexed_chunks / source_chunks) if source_chunks else 0.0,
            "safe_sample_limit": SAMPLE_CHUNK_LIMIT,
            "knowledge_index_statistics": index_statistics,
        },
    }


def _enterprise_search(
    dashboard: dict[str, Any],
    chunk_overview: dict[str, Any],
    fts_health: dict[str, Any],
) -> dict[str, Any]:
    operational = dashboard.get("operational_summary") if isinstance(dashboard.get("operational_summary"), dict) else {}
    search_readiness = (
        operational.get("search_readiness") if isinstance(operational.get("search_readiness"), dict) else {}
    )
    searchable_chunks = int(chunk_overview.get("indexed_chunks") or 0)
    indexed_documents = int(operational.get("indexed_documents") or operational.get("indexed_knowledge_documents") or 0)
    fts_ready = bool(fts_health.get("fts_healthy")) or bool(search_readiness.get("ready")) or searchable_chunks > 0
    return {
        "fts_ready": fts_ready,
        "search_ready": fts_ready,
        "indexed_document_count": indexed_documents,
        "searchable_chunk_count": searchable_chunks,
        "search_diagnostics": {
            "postgresql_fts_source": True,
            "knowledge_fts_health": fts_health,
            "search_readiness": search_readiness,
            "qdrant_used": False,
            "llm_used": False,
        },
    }


def _diagnostics(
    collections: list[dict[str, Any]],
    knowledge_sources: list[dict[str, Any]],
    enterprise_search: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any]:
    dashboard_diagnostics = (
        dashboard.get("alerts_and_diagnostics") if isinstance(dashboard.get("alerts_and_diagnostics"), dict) else {}
    )
    degraded_items: list[dict[str, Any]] = []
    for collection in collections:
        readiness = collection.get("readiness") if isinstance(collection.get("readiness"), dict) else {}
        if readiness.get("status") != "ready":
            degraded_items.append(
                {
                    "item_type": "collection",
                    "item_id": collection.get("collection_id"),
                    "status": readiness.get("status"),
                    "reason": "collection_not_search_ready",
                }
            )
    for source in knowledge_sources:
        if source.get("readiness") != "ready":
            degraded_items.append(
                {
                    "item_type": "knowledge_source",
                    "item_id": source.get("source_id"),
                    "status": source.get("readiness"),
                    "reason": "knowledge_source_not_ready",
                }
            )
    if not enterprise_search.get("search_ready"):
        degraded_items.append(
            {
                "item_type": "enterprise_search",
                "item_id": "postgres_fts",
                "status": "pending",
                "reason": "no_searchable_chunks",
            }
        )
    return {
        "blocking_issues": dashboard_diagnostics.get("blocking_issues") or [],
        "warnings": dashboard_diagnostics.get("warnings") or [],
        "pending_capabilities": dashboard_diagnostics.get("pending_capabilities") or [],
        "degraded_items": degraded_items,
    }


def build_knowledge_workspace_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
    source_runtimes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = source_runtimes or {}
    dashboard = sources.get("dashboard") or (
        build_platform_dashboard_runtime(
            db,
            organization_id=organization_id,
            platform_scope=True,
        )
        if platform_scope
        else {}
    )
    index_health = build_knowledge_index_health(db) if platform_scope else {"scope": "organization"}
    index_statistics = build_knowledge_index_statistics(db) if platform_scope else {"scope": "organization"}
    fts_health = build_knowledge_fts_health(db) if platform_scope else {"postgresql_fts_available": True}
    readiness = dashboard.get("readiness_summary") if isinstance(dashboard.get("readiness_summary"), dict) else {}
    record_statement = select(DocumentRecord)
    if not platform_scope:
        record_statement = record_statement.where(DocumentRecord.organization_id == organization_id)
    scoped_records = [record for record in db.scalars(record_statement).all() if not _is_validation_document(record)]
    record_ids = [str(record.id) for record in scoped_records]
    collections = _collections(db, organization_id=organization_id, platform_scope=platform_scope)
    knowledge_sources = _knowledge_sources(db, organization_id=organization_id, platform_scope=platform_scope)
    knowledge_documents = _knowledge_documents(db, record_ids=record_ids, platform_scope=False)
    knowledge_document_ids = [uuid.UUID(str(item["knowledge_document_id"])) for item in knowledge_documents]
    chunk_overview = _chunk_overview(
        db,
        {"health": index_health, "statistics": index_statistics},
        organization_id=organization_id,
        platform_scope=False,
        knowledge_document_ids=knowledge_document_ids,
    )
    enterprise_search = _enterprise_search(dashboard if platform_scope else {}, chunk_overview, fts_health)
    if not platform_scope:
        enterprise_search["indexed_document_count"] = len(knowledge_documents)
    diagnostics = _diagnostics(collections, knowledge_sources, enterprise_search, dashboard)
    knowledge_ready = (bool(readiness.get("knowledge_ready")) if platform_scope else False) or bool(knowledge_documents)
    search_ready = (bool(readiness.get("search_ready")) if platform_scope else False) or bool(
        enterprise_search.get("search_ready")
    )
    citations_evidence_ready = bool(chunk_overview.get("indexed_chunks")) and bool(knowledge_documents)
    runtime_ready = knowledge_ready and search_ready and not diagnostics["blocking_issues"]
    return {
        "knowledge_workspace_runtime_schema_version": KNOWLEDGE_WORKSPACE_RUNTIME_SCHEMA_VERSION,
        "runtime_name": KNOWLEDGE_WORKSPACE_RUNTIME_NAME,
        "runtime_status": "ready" if runtime_ready else "degraded",
        "workspace_summary": {
            "metric_scope": "platform" if platform_scope else "selected_organization",
            "organization_id": None if platform_scope else organization_id,
            "included_data_origins": ["platform"] if platform_scope else ["operational", "reference"],
            "runtime_status": "ready" if runtime_ready else "degraded",
            "knowledge_ready": knowledge_ready,
            "search_ready": search_ready,
            "postgresql_source_of_truth": True,
            "ai_required": False,
            "llm_used": False,
            "qdrant_used": False,
            "citations_evidence_ready": citations_evidence_ready,
        },
        "collections": collections,
        "knowledge_sources": knowledge_sources,
        "knowledge_documents": knowledge_documents,
        "chunk_overview": chunk_overview,
        "enterprise_search": enterprise_search,
        "diagnostics": diagnostics,
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "qdrant_used": False,
    }
