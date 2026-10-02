from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import Organization
from app.models.documents import Artifact, Chunk, Collection, DocumentRecord, DocumentType, DocumentVersion
from app.models.knowledge_index import KnowledgeChunk, KnowledgeDocument
from app.models.processing import ProcessingRevision
from app.services.knowledge_workspace_runtime import build_knowledge_workspace_runtime
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime
from app.services.source_compatibility import FORMAT_REGISTRY, CompatibilityLevel

DOCUMENT_WORKSPACE_RUNTIME_SCHEMA_VERSION = "1"
DOCUMENT_WORKSPACE_RUNTIME_NAME = "document_workspace_runtime"
READY_STATUSES = {"ready", "indexed", "completed", "published", "verified", "stored"}


def _count_by(db: Session, model: Any, column: Any, *criteria: Any) -> dict[str, int]:
    statement = select(column, func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    rows = db.execute(statement.group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _uuid_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _latest_by(items: list[Any], key: str) -> dict[uuid.UUID, Any]:
    grouped: dict[uuid.UUID, Any] = {}
    for item in items:
        group_id = getattr(item, key)
        current = grouped.get(group_id)
        if current is None or getattr(item, "created_at", None) > getattr(current, "created_at", None):
            grouped[group_id] = item
    return grouped


def _status_ready(status: str | None) -> bool:
    return str(status or "").lower() in READY_STATUSES


def _is_validation_document(record: DocumentRecord) -> bool:
    source = record.source_ref or {}
    return bool(
        source.get("execution_key")
        or source.get("scenario") == "local_product_acceptance"
        or source.get("smoke")
        or source.get("provider") == "smoke"
    )


def _knowledge_maps(
    knowledge_documents: list[KnowledgeDocument],
    knowledge_chunks: list[KnowledgeChunk],
) -> tuple[dict[str, KnowledgeDocument], dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    documents_by_version: dict[str, KnowledgeDocument] = {}
    total_chunks_by_document: dict[uuid.UUID, int] = defaultdict(int)
    indexed_chunks_by_document: dict[uuid.UUID, int] = defaultdict(int)
    for document in knowledge_documents:
        if document.document_version_id:
            documents_by_version[str(document.document_version_id)] = document
    for chunk in knowledge_chunks:
        total_chunks_by_document[chunk.knowledge_document_id] += 1
        if chunk.status in ("indexed", "ready"):
            indexed_chunks_by_document[chunk.knowledge_document_id] += 1
    return documents_by_version, total_chunks_by_document, indexed_chunks_by_document


def _version_lifecycle(
    version: DocumentVersion,
    artifact: Artifact | None,
    processing_revision: ProcessingRevision | None,
    chunk_count: int,
    indexed_chunk_count: int,
    knowledge_document: KnowledgeDocument | None,
) -> dict[str, bool]:
    snapshot = version.source_snapshot or {}
    stored = bool(snapshot.get("storage_verified")) or bool(version.object_store_key)
    processed = processing_revision is not None and processing_revision.status in ("completed", "succeeded")
    chunked = chunk_count > 0
    indexed = knowledge_document is not None and indexed_chunk_count > 0
    searchable = indexed
    historical_persisted = searchable and processing_revision is None and chunk_count == 0
    return {
        "registered": True,
        "planned": True,
        "uploaded": bool(snapshot.get("file_uploaded")) or artifact is not None,
        "stored": stored,
        "processed": processed,
        "historical_persisted": historical_persisted,
        "chunked": chunked,
        "published": knowledge_document is not None,
        "indexed": indexed,
        "searchable": searchable,
        "assistant_ready": searchable,
        "chat_ready": searchable,
    }


def _current_lifecycle_status(
    record_status: str,
    version_status: str | None,
    processing_status: str | None,
    knowledge_status: str | None,
    readiness: dict[str, bool],
) -> str:
    persisted_statuses = {
        str(status or "").strip().lower()
        for status in (record_status, version_status, processing_status, knowledge_status)
        if status
    }
    if "archived" in persisted_statuses:
        return "archived"
    if persisted_statuses.intersection({"failed", "error", "blocked", "cancelled"}):
        return "failed"
    if readiness.get("searchable"):
        return "searchable"
    if readiness.get("indexed"):
        return "indexed"
    if readiness.get("published"):
        return "published"
    if persisted_statuses.intersection({"pending", "queued", "prepared", "running", "processing", "in_progress"}):
        return "pending"
    if readiness.get("processed"):
        return "processed"
    if readiness.get("stored"):
        return "stored"
    if readiness.get("uploaded"):
        return "uploaded"
    return str(record_status or version_status or "registered").strip().lower()


def _registry_item(
    record: DocumentRecord,
    version: DocumentVersion | None,
    document_type: DocumentType | None,
    organization: Organization | None,
    collection: Collection | None,
    lifecycle: dict[str, bool] | None,
    processing_revision: ProcessingRevision | None,
    knowledge_document: KnowledgeDocument | None,
) -> dict[str, Any]:
    readiness = lifecycle or {}
    return {
        "document_record_id": record.id,
        "external_reference": record.external_reference,
        "title": record.title,
        "document_type": {
            "document_type_id": document_type.id if document_type else record.document_type_id,
            "code": document_type.code if document_type else None,
            "name": document_type.name if document_type else None,
        },
        "organization": {
            "organization_id": organization.id if organization else record.organization_id,
            "slug": organization.slug if organization else None,
            "name": organization.name if organization else None,
        },
        "collection": {
            "collection_id": collection.id if collection else record.collection_id,
            "code": collection.code if collection else None,
            "name": collection.name if collection else None,
        },
        "status": record.status,
        "lifecycle_status": _current_lifecycle_status(
            record.status,
            version.status if version else None,
            processing_revision.status if processing_revision else None,
            knowledge_document.status if knowledge_document else None,
            readiness,
        ),
        "classification": record.classification or {},
        "current_version": {
            "document_version_id": version.id if version else None,
            "version": version.version_number if version else None,
            "status": version.status if version else None,
        },
        "latest_activity": version.updated_at if version else record.updated_at,
        "readiness": {
            "status": "ready" if readiness.get("searchable") and readiness.get("chat_ready") else "pending",
            "storage_ready": bool(readiness.get("stored")),
            "processing_ready": bool(readiness.get("processed")),
            "knowledge_ready": bool(readiness.get("indexed")),
            "search_ready": bool(readiness.get("searchable")),
            "assistant_ready": bool(readiness.get("assistant_ready")),
            "chat_ready": bool(readiness.get("chat_ready")),
        },
    }


def build_document_workspace_runtime(
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
    knowledge_workspace = sources.get("knowledge") or build_knowledge_workspace_runtime(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
        source_runtimes={"dashboard": dashboard} if dashboard else None,
    )
    owned = () if platform_scope else (DocumentRecord.organization_id == organization_id,)
    version_owned = () if platform_scope else (DocumentVersion.organization_id == organization_id,)
    artifact_owned = () if platform_scope else (Artifact.organization_id == organization_id,)
    chunk_owned = () if platform_scope else (Chunk.organization_id == organization_id,)
    processing_owned = () if platform_scope else (ProcessingRevision.organization_id == organization_id,)
    records = list(
        db.scalars(
            select(DocumentRecord).where(*owned).order_by(DocumentRecord.updated_at.desc(), DocumentRecord.id.asc())
        ).all()
    )
    records = [record for record in records if not _is_validation_document(record)]
    operational_record_ids = [record.id for record in records]
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(*version_owned, DocumentVersion.document_record_id.in_(operational_record_ids))
            .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        ).all()
    )
    operational_version_ids = [version.id for version in versions]
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(*artifact_owned, Artifact.document_version_id.in_(operational_version_ids))
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        ).all()
    )
    chunks = list(
        db.scalars(
            select(Chunk)
            .where(*chunk_owned, Chunk.document_version_id.in_(operational_version_ids))
            .order_by(Chunk.created_at.asc(), Chunk.id.asc())
        ).all()
    )
    processing_revisions = list(
        db.scalars(
            select(ProcessingRevision)
            .where(*processing_owned, ProcessingRevision.document_version_id.in_(operational_version_ids))
            .order_by(ProcessingRevision.created_at.asc(), ProcessingRevision.id.asc())
        ).all()
    )
    record_ids = [str(item.id) for item in records]
    knowledge_document_criteria = (KnowledgeDocument.document_record_id.in_(record_ids),)
    knowledge_documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .where(*knowledge_document_criteria)
            .order_by(KnowledgeDocument.created_at.asc(), KnowledgeDocument.id.asc())
        ).all()
    )
    knowledge_document_ids = [item.id for item in knowledge_documents]
    knowledge_chunk_criteria = (KnowledgeChunk.knowledge_document_id.in_(knowledge_document_ids),)
    knowledge_chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(*knowledge_chunk_criteria)
            .order_by(KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
        ).all()
    )
    organizations = {
        item.id: item
        for item in db.scalars(
            select(Organization).where(Organization.id.in_([record.organization_id for record in records]))
        ).all()
    }
    document_types = {
        item.id: item
        for item in db.scalars(
            select(DocumentType).where(
                DocumentType.id.in_([record.document_type_id for record in records if record.document_type_id])
            )
        ).all()
    }
    collections = {
        item.id: item
        for item in db.scalars(
            select(Collection).where(
                Collection.id.in_([record.collection_id for record in records if record.collection_id])
            )
        ).all()
    }

    latest_version_by_record = _latest_by(versions, "document_record_id")
    artifact_by_version = _latest_by(artifacts, "document_version_id")
    processing_by_version = _latest_by(processing_revisions, "document_version_id")
    chunks_by_version: dict[uuid.UUID, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_version[chunk.document_version_id].append(chunk)
    knowledge_by_version, knowledge_chunk_count, indexed_knowledge_chunk_count = _knowledge_maps(
        knowledge_documents,
        knowledge_chunks,
    )

    version_items: list[dict[str, Any]] = []
    lifecycle_by_version: dict[uuid.UUID, dict[str, bool]] = {}
    for version in versions:
        artifact = artifact_by_version.get(version.id)
        processing_revision = processing_by_version.get(version.id)
        version_chunks = chunks_by_version.get(version.id, [])
        indexed_document_chunks = len([item for item in version_chunks if item.status == "indexed"])
        knowledge_document = knowledge_by_version.get(str(version.id))
        total_knowledge_chunks = knowledge_chunk_count.get(knowledge_document.id, 0) if knowledge_document else 0
        indexed_knowledge_chunks = (
            indexed_knowledge_chunk_count.get(knowledge_document.id, 0) if knowledge_document else 0
        )
        lifecycle = _version_lifecycle(
            version,
            artifact,
            processing_revision,
            len(version_chunks),
            indexed_knowledge_chunks,
            knowledge_document,
        )
        lifecycle_by_version[version.id] = lifecycle
        storage_verified = lifecycle["stored"]
        chunks_ready = lifecycle["chunked"]
        knowledge_ready = lifecycle["indexed"]
        search_ready = lifecycle["searchable"]
        source_snapshot = version.source_snapshot or {}
        version_items.append(
            {
                "document_version_id": version.id,
                "document_record_id": version.document_record_id,
                "version": version.version_number,
                "created_at": version.created_at,
                "uploaded_at": version.updated_at if source_snapshot.get("file_uploaded") else None,
                "storage_status": "verified" if storage_verified else "pending",
                "processing_status": processing_revision.status if processing_revision else (
                    "historical_persisted" if lifecycle["historical_persisted"] else "pending"
                ),
                "chunk_status": "ready" if chunks_ready else "pending",
                "knowledge_publication_status": knowledge_document.status if knowledge_document else "pending",
                "knowledge_index_status": "indexed" if knowledge_ready else "pending",
                "enterprise_search_status": "ready" if search_ready else "pending",
                "reference_tenant_status": "ready" if source_snapshot.get("reference_tenant") else "not_applicable",
                "lifecycle": lifecycle,
                "storage": {
                    "provider": version.object_store_provider or (artifact.object_store_provider if artifact else None),
                    "bucket": version.object_store_bucket or (artifact.bucket if artifact else None),
                    "object_key": version.object_store_key or (artifact.object_key if artifact else None),
                    "status": "verified" if storage_verified else "pending",
                    "storage_reused": bool(source_snapshot.get("storage_reused")),
                    "storage_verification": storage_verified,
                    "verification_diagnostics": {
                        "checksum_sha256": version.checksum_sha256 or (artifact.checksum_sha256 if artifact else None),
                        "size_bytes": version.size_bytes or (artifact.size_bytes if artifact else None),
                        "content_type": version.content_type or (artifact.media_type if artifact else None),
                    },
                },
                "processing": {
                    "state": processing_revision.status if processing_revision else (
                        "historical_persisted" if lifecycle["historical_persisted"] else "pending"
                    ),
                    "lineage": "modern_execution" if processing_revision else (
                        "historical_persisted" if lifecycle["historical_persisted"] else "not_observed"
                    ),
                    "processing_execution": _uuid_string(processing_revision.runtime_execution_id)
                    if processing_revision
                    else None,
                    "processing_duration": None
                    if not processing_revision or not processing_revision.completed_at
                    else str(processing_revision.completed_at - processing_revision.started_at),
                    "processing_diagnostics": {
                        "content_unit_count": processing_revision.content_unit_count if processing_revision else 0,
                        "chunk_count": processing_revision.chunk_count if processing_revision else 0,
                    },
                },
                "chunks": {
                    "chunk_count": len(version_chunks),
                    "indexed_chunk_count": indexed_document_chunks,
                    "knowledge_indexed_chunk_count": indexed_knowledge_chunks,
                    "chunk_readiness": "ready" if chunks_ready else "pending",
                    "chunk_diagnostics": {
                        "document_chunk_statuses": {
                            status: len([item for item in version_chunks if item.status == status])
                            for status in sorted({item.status for item in version_chunks})
                        },
                        "knowledge_chunk_count": total_knowledge_chunks,
                    },
                },
                "knowledge": {
                    "knowledge_publication": knowledge_document is not None,
                    "knowledge_document": knowledge_document.id if knowledge_document else None,
                    "knowledge_readiness": "ready" if knowledge_ready else "pending",
                    "publication_diagnostics": {
                        "publication_id": knowledge_document.publication_id if knowledge_document else None,
                        "content_signature": knowledge_document.content_signature if knowledge_document else None,
                    },
                },
                "enterprise_search": {
                    "fts_readiness": search_ready,
                    "knowledge_index_readiness": knowledge_ready,
                    "enterprise_search_readiness": "ready" if search_ready else "pending",
                    "search_diagnostics": {
                        "searchable_chunk_count": indexed_knowledge_chunks,
                        "postgresql_fts_source": True,
                    },
                },
            }
        )

    registry = []
    for record in records:
        version = latest_version_by_record.get(record.id)
        processing_revision = processing_by_version.get(version.id) if version else None
        knowledge_document = knowledge_by_version.get(str(version.id)) if version else None
        registry.append(
            _registry_item(
                record,
                version,
                document_types.get(record.document_type_id),
                organizations.get(record.organization_id),
                collections.get(record.collection_id),
                lifecycle_by_version.get(version.id) if version else None,
                processing_revision,
                knowledge_document,
            )
        )

    lifecycle_counts = {
        key: len([item for item in lifecycle_by_version.values() if item.get(key)])
        for key in (
            "registered",
            "planned",
            "uploaded",
            "stored",
            "processed",
            "historical_persisted",
            "chunked",
            "published",
            "indexed",
            "searchable",
            "assistant_ready",
            "chat_ready",
        )
    }
    dashboard_readiness = (
        dashboard.get("readiness_summary") if isinstance(dashboard.get("readiness_summary"), dict) else {}
    )
    knowledge_summary = (
        knowledge_workspace.get("workspace_summary")
        if isinstance(knowledge_workspace.get("workspace_summary"), dict)
        else {}
    )
    documents_ready = (bool(dashboard_readiness.get("documents_ready")) if platform_scope else False) or bool(records)
    processing_ready = not processing_revisions or any(
        item.status in ("completed", "succeeded") for item in processing_revisions
    )
    knowledge_ready = bool(knowledge_summary.get("knowledge_ready")) or bool(knowledge_documents)
    search_ready = bool(knowledge_summary.get("search_ready")) or lifecycle_counts["searchable"] > 0
    runtime_ready = documents_ready and processing_ready and knowledge_ready and search_ready
    blocking_issues = (
        []
        if runtime_ready
        else [
            {
                "code": "document_workspace_not_fully_ready",
                "component": "document_workspace",
                "message": "One or more document lifecycle domains are not ready.",
            }
        ]
    )
    diagnostics = {
        "blocking_issues": blocking_issues,
        "warnings": [],
        "pending_capabilities": [],
        "lifecycle_diagnostics": {
            "versions_by_status": _count_by(db, DocumentVersion, DocumentVersion.status, *version_owned),
            "artifacts_by_status": _count_by(db, Artifact, Artifact.status, *artifact_owned),
            "processing_by_status": _count_by(db, ProcessingRevision, ProcessingRevision.status, *processing_owned),
            "chunks_by_status": _count_by(db, Chunk, Chunk.status, *chunk_owned),
            "knowledge_documents_by_status": _count_by(
                db, KnowledgeDocument, KnowledgeDocument.status, *knowledge_document_criteria
            ),
        },
    }
    return {
        "document_workspace_runtime_schema_version": DOCUMENT_WORKSPACE_RUNTIME_SCHEMA_VERSION,
        "runtime_name": DOCUMENT_WORKSPACE_RUNTIME_NAME,
        "runtime_status": "ready" if runtime_ready else "degraded",
        "workspace_summary": {
            "runtime_status": "ready" if runtime_ready else "degraded",
            "documents_ready": documents_ready,
            "processing_ready": processing_ready,
            "knowledge_ready": knowledge_ready,
            "search_ready": search_ready,
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "qdrant_used": False,
        },
        "document_registry": registry,
        "versions": version_items,
        "upload_capabilities": {
            "accepted_extensions": sorted(
                {
                    extension
                    for source_format in FORMAT_REGISTRY
                    if source_format.compatibility == CompatibilityLevel.NATIVE
                    for extension in source_format.extensions
                }
            ),
            "accepted_media_types": sorted(
                {
                    media_type
                    for source_format in FORMAT_REGISTRY
                    if source_format.compatibility == CompatibilityLevel.NATIVE
                    for media_type in source_format.media_types
                }
            ),
            "contract_source": "source_compatibility_registry",
        },
        "lifecycle": {"counts": lifecycle_counts, "versions": version_items},
        "storage": {
            "stored_versions": lifecycle_counts["stored"],
            "storage_provider_counts": _count_by(
                db, DocumentVersion, DocumentVersion.object_store_provider, *version_owned
            ),
            "storage_status": "ready" if lifecycle_counts["stored"] else "pending",
            "storage_verification": lifecycle_counts["stored"] > 0,
            "verification_diagnostics": {
                "artifacts": len(artifacts),
                "verified_artifacts": len([item for item in artifacts if _status_ready(item.status)]),
            },
        },
        "processing": {
            "processing_state": "ready" if processing_ready else "pending",
            "processing_executions": len(processing_revisions),
            "historical_persisted_versions": lifecycle_counts["historical_persisted"],
            "processing_diagnostics": diagnostics["lifecycle_diagnostics"]["processing_by_status"],
        },
        "chunks": {
            "source_chunk_count": len(chunks),
            "knowledge_chunk_count": len(knowledge_chunks),
            "indexed_knowledge_chunk_count": len(
                [item for item in knowledge_chunks if item.status in {"indexed", "ready"}]
            ),
            "chunk_count": len(chunks),
            "indexed_chunk_count": len([item for item in chunks if item.status == "indexed"]),
            "chunk_readiness": "ready" if lifecycle_counts["chunked"] else "pending",
            "chunk_diagnostics": diagnostics["lifecycle_diagnostics"]["chunks_by_status"],
        },
        "knowledge": {
            "knowledge_publication": bool(knowledge_documents),
            "knowledge_documents": len(knowledge_documents),
            "knowledge_chunks": len(knowledge_chunks),
            "knowledge_readiness": "ready" if knowledge_ready else "pending",
            "publication_diagnostics": diagnostics["lifecycle_diagnostics"]["knowledge_documents_by_status"],
        },
        "enterprise_search": {
            "fts_readiness": search_ready,
            "knowledge_index_readiness": knowledge_ready,
            "enterprise_search_readiness": "ready" if search_ready else "pending",
            "search_diagnostics": {
                "searchable_versions": lifecycle_counts["searchable"],
                "postgresql_fts_source": True,
            },
        },
        "diagnostics": diagnostics,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
    }
