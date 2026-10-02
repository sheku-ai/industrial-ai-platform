"""Executable Knowledge Lifecycle Runtime."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.knowledge_index_runtime import build_knowledge_index
from app.services.knowledge_lifecycle_gateway import build_knowledge_lifecycle_gateway
from app.services.knowledge_lifecycle_session import KNOWLEDGE_LIFECYCLE_RUNTIME_VERSION

KNOWLEDGE_LIFECYCLE_RUNTIME_SCHEMA_VERSION = "1"
LIFECYCLE_STATUS_BLOCKED = "blocked"
LIFECYCLE_STATUS_COMPLETED = "completed"


@dataclass(frozen=True)
class KnowledgeLifecycleRuntimeResult:
    lifecycle_status: str
    lifecycle_completed: bool
    lifecycle_succeeded: bool
    operation: str
    mode: str
    decision: str
    documents_scanned: int = 0
    documents_updated: int = 0
    documents_invalidated: int = 0
    documents_deleted: int = 0
    chunks_scanned: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    duplicates_removed: int = 0
    orphan_chunks_removed: int = 0
    stale_documents_removed: int = 0
    obsolete_publications_removed: int = 0
    change_detection: dict[str, Any] = field(default_factory=dict)
    index_result: dict[str, Any] = field(default_factory=dict)
    cleanup_result: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)
    lifecycle_run: dict[str, Any] | None = None
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _stable_digest(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _published_chunks(publication_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(publication_result, dict):
        return []
    chunks = publication_result.get("published_chunks")
    return chunks if isinstance(chunks, list) else []


def _content_signature(chunks: list[dict[str, Any]]) -> str:
    seed = "|".join(
        f"{chunk.get('chunk_index')}:{chunk.get('published_chunk_id')}:{chunk.get('content_hash')}" for chunk in chunks
    )
    return _stable_digest(seed)


def _document_to_dict(document: Any) -> dict[str, Any]:
    return {
        "knowledge_document_id": str(document.id),
        "artifact_id": document.artifact_id,
        "publication_id": document.publication_id,
        "document_record_id": document.document_record_id,
        "document_version_id": document.document_version_id,
        "status": document.status,
        "version": document.version,
        "content_signature": document.content_signature,
        "metadata": document.metadata_json or {},
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


def _chunk_to_dict(chunk: Any) -> dict[str, Any]:
    return {
        "knowledge_chunk_id": str(chunk.id),
        "knowledge_document_id": str(chunk.knowledge_document_id),
        "published_chunk_id": chunk.published_chunk_id,
        "publication_id": chunk.publication_id,
        "artifact_id": chunk.artifact_id,
        "chunk_index": chunk.chunk_index,
        "content_hash": chunk.content_hash,
        "semantic_hash": chunk.semantic_hash,
        "status": chunk.status,
        "metadata": chunk.metadata_json or {},
    }


def _run_to_dict(run: Any) -> dict[str, Any]:
    return {
        "knowledge_lifecycle_run_id": str(run.id),
        "lifecycle_session_id": run.lifecycle_session_id,
        "operation": run.operation,
        "mode": run.mode,
        "status": run.status,
        "artifact_id": run.artifact_id,
        "publication_id": run.publication_id,
        "document_id": run.document_id,
        "decision": run.decision,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _snapshot_health(db: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    repository = KnowledgeIndexRepository(db)
    health = repository.health_metrics()
    statistics = repository.statistics()
    repository.create_health_snapshot(health=health, statistics=statistics)
    return health, statistics


def _scope_documents(
    repository: KnowledgeIndexRepository,
    *,
    mode: str,
    artifact_id: str | None,
    publication_id: str | None,
    document_id: str | None,
) -> list[Any]:
    if mode == "FULL":
        return repository.list_documents(include_inactive=True)
    if mode == "DOCUMENT":
        return repository.list_documents(document_id=document_id, include_inactive=True)
    if mode == "PUBLICATION":
        return repository.list_documents(publication_id=publication_id, include_inactive=True)
    if mode == "ARTIFACT":
        return repository.list_documents(artifact_id=artifact_id, include_inactive=True)
    return repository.list_documents(artifact_id=artifact_id, publication_id=publication_id, include_inactive=True)


def detect_knowledge_changes(
    db: Session,
    *,
    mode: str,
    artifact_id: str | None = None,
    publication_id: str | None = None,
    document_id: str | None = None,
    publication_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = KnowledgeIndexRepository(db)
    chunks = _published_chunks(publication_result)
    resolved_artifact_id = (
        artifact_id
        or (publication_result or {}).get("artifact_id")
        or (chunks[0].get("artifact_id") if chunks else None)
    )
    resolved_publication_id = (
        publication_id
        or (publication_result or {}).get("publication_id")
        or (chunks[0].get("publication_id") if chunks else None)
    )
    documents = _scope_documents(
        repository,
        mode=mode,
        artifact_id=str(resolved_artifact_id) if resolved_artifact_id else None,
        publication_id=str(resolved_publication_id) if resolved_publication_id else None,
        document_id=document_id,
    )
    if publication_result and not documents and resolved_artifact_id:
        artifact_documents = repository.list_documents(artifact_id=str(resolved_artifact_id), include_inactive=True)
        documents = artifact_documents[-1:] if artifact_documents else []
    existing = documents[0] if documents else None
    existing_chunks = repository.list_chunks_for_document(existing.id) if existing is not None else []
    detected: list[str] = []
    action = "ignore"
    if publication_result and not chunks:
        action = "delete"
        detected.append("publication_chunks_missing")
    elif publication_result and existing is None:
        action = "update"
        detected.append("document_missing")
    elif publication_result and existing is not None:
        new_signature = _content_signature(chunks)
        publication_timestamp = max(
            (str(chunk.get("published_at")) for chunk in chunks if chunk.get("published_at")), default=None
        )
        existing_publication_timestamp = max(
            (
                str(chunk.metadata_json.get("published_at"))
                for chunk in existing_chunks
                if isinstance(chunk.metadata_json, dict) and chunk.metadata_json.get("published_at")
            ),
            default=None,
        )
        if existing.publication_id != str(resolved_publication_id):
            detected.append("publication_id")
        if existing.content_signature != new_signature:
            detected.append("content_hash")
        if len(existing_chunks) != len(chunks):
            detected.append("chunk_count")
        if publication_timestamp != existing_publication_timestamp:
            detected.append("publication_timestamp")
        existing_by_index = {chunk.chunk_index: chunk for chunk in existing_chunks}
        for chunk in chunks:
            current = existing_by_index.get(int(chunk.get("chunk_index")))
            if current is None:
                detected.append("chunk_missing")
                continue
            if current.content_hash != chunk.get("content_hash"):
                detected.append("content_hash")
            if current.semantic_hash != chunk.get("semantic_hash"):
                detected.append("semantic_hash")
            incoming_metadata = dict(chunk.get("metadata") or {})
            if chunk.get("published_at"):
                incoming_metadata["published_at"] = chunk.get("published_at")
            if chunk.get("source_content_sha256"):
                incoming_metadata["source_content_sha256"] = chunk.get("source_content_sha256")
            if current.metadata_json != incoming_metadata:
                detected.append("metadata")
        if existing.version and int(existing.version) > 1 and existing.content_signature != new_signature:
            detected.append("document_version")
        unique_changes = sorted(set(detected))
        if not unique_changes:
            action = "ignore"
        elif {"chunk_count", "publication_id", "document_version"}.intersection(unique_changes):
            action = "rebuild"
        else:
            action = "update"
        detected = unique_changes
    elif documents:
        stale_documents = [
            document for document in documents if document.status in {"stale", "invalidated", "obsolete"}
        ]
        duplicate_count = len(repository.duplicate_chunks())
        if stale_documents or duplicate_count:
            action = "rebuild"
            detected.extend(["stale_documents"] if stale_documents else [])
            detected.extend(["duplicate_chunks"] if duplicate_count else [])
    return {
        "change_detection_schema_version": "1",
        "mode": mode,
        "action": action,
        "decision": action,
        "detected_changes": sorted(set(detected)),
        "documents_scanned": len(documents),
        "chunks_scanned": len(existing_chunks),
        "publication_chunk_count": len(chunks),
        "publication_id": str(resolved_publication_id) if resolved_publication_id else None,
        "artifact_id": str(resolved_artifact_id) if resolved_artifact_id else None,
        "document": _document_to_dict(existing) if existing is not None else None,
    }


def _rebuild_documents(repository: KnowledgeIndexRepository, documents: list[Any]) -> tuple[int, int]:
    documents_updated = 0
    chunks_updated = 0
    for document in documents:
        chunks = repository.list_chunks_for_document(document.id)
        signature = _stable_digest(
            "|".join(f"{chunk.chunk_index}:{chunk.published_chunk_id}:{chunk.content_hash}" for chunk in chunks)
        )
        if document.content_signature != signature or document.status != "indexed":
            document.content_signature = signature
            document.status = "indexed"
            document.version = int(document.version or 1) + 1
            repository.session.add(document)
            documents_updated += 1
        for chunk in chunks:
            if chunk.status != "indexed":
                chunk.status = "indexed"
                repository.session.add(chunk)
                chunks_updated += 1
    repository.session.flush()
    return documents_updated, chunks_updated


def _cleanup(repository: KnowledgeIndexRepository, *, documents: list[Any] | None = None) -> dict[str, int]:
    scoped_documents = list(documents) if documents is not None else None
    stale_documents_removed, stale_chunks_removed = repository.cleanup_stale_documents(scoped_documents)
    if scoped_documents is not None:
        scoped_ids = {
            document.id for document in scoped_documents if document.status not in {"stale", "invalidated", "obsolete"}
        }
        scoped_documents = [
            document for document in repository.list_documents(include_inactive=True) if document.id in scoped_ids
        ]
    orphan_chunks_removed = repository.cleanup_orphan_chunks()
    duplicates_removed = repository.cleanup_duplicate_chunks(documents=scoped_documents)
    obsolete_publications_removed, obsolete_chunks_removed = repository.cleanup_obsolete_publications(scoped_documents)
    return {
        "orphan_chunks_removed": orphan_chunks_removed,
        "duplicates_removed": duplicates_removed,
        "stale_documents_removed": stale_documents_removed,
        "obsolete_publications_removed": obsolete_publications_removed,
        "documents_deleted": stale_documents_removed + obsolete_publications_removed,
        "chunks_deleted": orphan_chunks_removed + stale_chunks_removed + obsolete_chunks_removed,
    }


def serialize_knowledge_lifecycle_result(result: KnowledgeLifecycleRuntimeResult) -> dict[str, Any]:
    return {
        "knowledge_lifecycle_runtime_schema_version": KNOWLEDGE_LIFECYCLE_RUNTIME_SCHEMA_VERSION,
        "knowledge_lifecycle_runtime_version": KNOWLEDGE_LIFECYCLE_RUNTIME_VERSION,
        "lifecycle_status": result.lifecycle_status,
        "lifecycle_completed": result.lifecycle_completed,
        "lifecycle_succeeded": result.lifecycle_succeeded,
        "operation": result.operation,
        "mode": result.mode,
        "decision": result.decision,
        "documents_scanned": result.documents_scanned,
        "documents_updated": result.documents_updated,
        "documents_invalidated": result.documents_invalidated,
        "documents_deleted": result.documents_deleted,
        "chunks_scanned": result.chunks_scanned,
        "chunks_updated": result.chunks_updated,
        "chunks_deleted": result.chunks_deleted,
        "duplicates_removed": result.duplicates_removed,
        "orphan_chunks_removed": result.orphan_chunks_removed,
        "stale_documents_removed": result.stale_documents_removed,
        "obsolete_publications_removed": result.obsolete_publications_removed,
        "change_detection": dict(result.change_detection),
        "index_result": dict(result.index_result),
        "cleanup_result": dict(result.cleanup_result),
        "health": dict(result.health),
        "statistics": dict(result.statistics),
        "lifecycle_run": result.lifecycle_run,
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "embeddings_created": False,
        "semantic_search_used": False,
        "qdrant_used": False,
        "postgres_fts_used": False,
        "ai_required": False,
        "persistence_status": "persisted" if result.lifecycle_succeeded else "not_persisted",
    }


def _persist_lifecycle_snapshot(db: Session, payload: dict[str, Any], *, artifact_id: str | None) -> dict[str, Any]:
    from app.services.runtime_persistence_runtime import persist_runtime_outputs

    lifecycle_run_id = payload.get("lifecycle_run", {}).get("knowledge_lifecycle_run_id")
    execution_id = f"knowledge-lifecycle:{payload.get('operation')}:{payload.get('mode')}:{lifecycle_run_id}"
    return persist_runtime_outputs(
        db,
        execution_id=execution_id,
        artifact_id=artifact_id,
        runtime_outputs={"knowledge_lifecycle": payload},
    )


def build_knowledge_lifecycle(
    db: Session,
    *,
    operation: str,
    mode: str = "INCREMENTAL",
    artifact_id: str | None = None,
    publication_id: str | None = None,
    document_id: str | None = None,
    publication_result: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_knowledge_lifecycle_gateway(
        operation=operation,
        mode=mode,
        artifact_id=artifact_id,
        publication_id=publication_id,
        document_id=document_id,
        publication_result=publication_result,
    )
    lifecycle_session = gateway.get("lifecycle_session") if isinstance(gateway.get("lifecycle_session"), dict) else {}
    if gateway.get("blocking_issues"):
        result = KnowledgeLifecycleRuntimeResult(
            lifecycle_status=LIFECYCLE_STATUS_BLOCKED,
            lifecycle_completed=False,
            lifecycle_succeeded=False,
            operation=operation,
            mode=str(mode or "INCREMENTAL").upper(),
            decision="blocked",
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=gateway.get("warnings") or [],
        )
        return {**serialize_knowledge_lifecycle_result(result), "knowledge_lifecycle_gateway": gateway}

    repository = KnowledgeIndexRepository(db)
    normalized_mode = str(mode or "INCREMENTAL").upper()
    change_detection = detect_knowledge_changes(
        db,
        mode=normalized_mode,
        artifact_id=artifact_id,
        publication_id=publication_id,
        document_id=document_id,
        publication_result=publication_result,
    )
    decision = str(change_detection.get("decision") or "ignore")
    index_result: dict[str, Any] = {}
    cleanup_result: dict[str, Any] = {}
    documents_updated = 0
    chunks_updated = 0
    documents_invalidated = 0
    documents_deleted = 0
    chunks_deleted = 0
    operation_name = lifecycle_session.get("operation") or operation

    if (
        operation_name in {"initial_indexing", "incremental"}
        and publication_result
        and decision in {"update", "rebuild"}
    ):
        index_result = build_knowledge_index(db, publication_result)
        documents_updated = 1 if index_result.get("document_indexed") else 0
        chunks_updated = int(index_result.get("chunks_created") or 0) + int(index_result.get("chunks_updated") or 0)
    elif operation_name == "reindex":
        if publication_result:
            index_result = build_knowledge_index(db, publication_result)
            documents_updated = 1 if index_result.get("document_indexed") else 0
            chunks_updated = int(index_result.get("chunks_created") or 0) + int(index_result.get("chunks_updated") or 0)
        else:
            documents = _scope_documents(
                repository,
                mode=normalized_mode,
                artifact_id=artifact_id,
                publication_id=publication_id,
                document_id=document_id,
            )
            documents_updated, chunks_updated = _rebuild_documents(repository, documents)
            decision = "rebuild" if documents else "ignore"
    elif operation_name == "cleanup":
        documents = _scope_documents(
            repository,
            mode=normalized_mode,
            artifact_id=artifact_id,
            publication_id=publication_id,
            document_id=document_id,
        )
        cleanup_result = _cleanup(repository, documents=documents if normalized_mode != "FULL" else None)
        documents_deleted = int(cleanup_result.get("documents_deleted") or 0)
        chunks_deleted = int(cleanup_result.get("chunks_deleted") or 0)
        decision = (
            "delete" if documents_deleted or chunks_deleted or cleanup_result.get("duplicates_removed") else "ignore"
        )
    elif operation_name == "rebuild":
        documents = _scope_documents(
            repository,
            mode=normalized_mode,
            artifact_id=artifact_id,
            publication_id=publication_id,
            document_id=document_id,
        )
        documents_invalidated = repository.invalidate_documents(documents, status="stale")
        repository.invalidate_chunks_for_documents(documents, status="stale")
        documents_updated, chunks_updated = _rebuild_documents(repository, documents)
        decision = "rebuild" if documents else "ignore"
    elif operation_name in {"health", "statistics"}:
        decision = "ignore"

    health, statistics = _snapshot_health(db)
    base_result = {
        "documents_scanned": int(change_detection.get("documents_scanned") or 0),
        "documents_updated": documents_updated,
        "documents_invalidated": documents_invalidated,
        "documents_deleted": documents_deleted,
        "chunks_scanned": int(change_detection.get("chunks_scanned") or 0),
        "chunks_updated": chunks_updated,
        "chunks_deleted": chunks_deleted,
        "duplicates_removed": int(cleanup_result.get("duplicates_removed") or 0),
        "orphan_chunks_removed": int(cleanup_result.get("orphan_chunks_removed") or 0),
        "stale_documents_removed": int(cleanup_result.get("stale_documents_removed") or 0),
        "obsolete_publications_removed": int(cleanup_result.get("obsolete_publications_removed") or 0),
    }
    run = repository.create_lifecycle_run(
        lifecycle_session_id=str(lifecycle_session.get("lifecycle_session_id")),
        operation=str(operation_name),
        mode=normalized_mode,
        status=LIFECYCLE_STATUS_COMPLETED,
        artifact_id=change_detection.get("artifact_id") or artifact_id,
        publication_id=change_detection.get("publication_id") or publication_id,
        document_id=document_id,
        decision=decision,
        result={**base_result, "decision": decision, "health": health, "statistics": statistics},
    )
    db.commit()
    result = KnowledgeLifecycleRuntimeResult(
        lifecycle_status=LIFECYCLE_STATUS_COMPLETED,
        lifecycle_completed=True,
        lifecycle_succeeded=True,
        operation=str(operation_name),
        mode=normalized_mode,
        decision=decision,
        change_detection=change_detection,
        index_result=index_result,
        cleanup_result=cleanup_result,
        health=health,
        statistics=statistics,
        lifecycle_run=_run_to_dict(run),
        warnings=gateway.get("warnings") or [],
        **base_result,
    )
    payload = {**serialize_knowledge_lifecycle_result(result), "knowledge_lifecycle_gateway": gateway}
    if persist_snapshot:
        payload["runtime_persistence"] = _persist_lifecycle_snapshot(
            db, payload, artifact_id=change_detection.get("artifact_id") or artifact_id
        )
    return payload


def build_knowledge_index_health(db: Session) -> dict[str, Any]:
    health, statistics = _snapshot_health(db)
    db.commit()
    return {
        "knowledge_index_health_schema_version": "1",
        "health": health,
        "statistics": statistics,
        "persistence_status": "persisted",
    }


def build_knowledge_index_statistics(db: Session) -> dict[str, Any]:
    repository = KnowledgeIndexRepository(db)
    statistics = repository.statistics()
    health = repository.health_metrics()
    repository.create_health_snapshot(health=health, statistics=statistics)
    db.commit()
    return {
        "knowledge_index_statistics_schema_version": "1",
        "statistics": statistics,
        "health": health,
        "persistence_status": "persisted",
    }
