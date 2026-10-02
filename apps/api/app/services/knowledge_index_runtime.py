"""Executable Knowledge Index Runtime."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.knowledge_publication import KnowledgePublicationEvidenceV1
from app.models.documents import Artifact, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimePersistenceRecord
from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.knowledge_index_gateway import build_knowledge_index_gateway
from app.services.knowledge_index_session import KNOWLEDGE_INDEX_RUNTIME_VERSION
from app.services.knowledge_publication_evidence_reader import read_knowledge_publication_evidence_v1
from app.services.knowledge_publication_index_gate import (
    evaluate_knowledge_publication_index_gate_v1,
    serialize_knowledge_publication_index_gate_v1,
)
from app.services.runtime_persistence_runtime import persist_runtime_outputs

KNOWLEDGE_INDEX_RUNTIME_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class KnowledgeIndexResult:
    index_status: str
    index_completed: bool
    index_succeeded: bool
    knowledge_document: dict[str, Any] | None
    knowledge_chunks: list[dict[str, Any]] = field(default_factory=list)
    knowledge_metadata: list[dict[str, Any]] = field(default_factory=list)
    chunks_indexed: int = 0
    chunks_created: int = 0
    chunks_updated: int = 0
    chunks_superseded: int = 0
    idempotent: bool = False
    reindex_performed: bool = False
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _content_signature(chunks: list[dict[str, Any]]) -> str:
    seed = "|".join(
        f"{chunk.get('chunk_index')}:{chunk.get('published_chunk_id')}:{chunk.get('content_hash')}" for chunk in chunks
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _document_metadata(
    publication_result: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    publication_evidence_id: uuid.UUID,
) -> dict[str, Any]:
    return {
        "lineage": {
            "artifact_id": publication_result.get("artifact_id") or (chunks[0].get("artifact_id") if chunks else None),
            "processing_session_id": publication_result.get("processing_session_id"),
            "chunk_session_id": publication_result.get("chunk_session_id"),
            "publication_id": publication_result.get("publication_id"),
            "publication_evidence_id": str(publication_evidence_id),
        },
        "hashes": {
            "content_signature": _content_signature(chunks),
            "chunk_hashes": [chunk.get("content_hash") for chunk in chunks],
            "semantic_hashes": [chunk.get("semantic_hash") for chunk in chunks],
        },
        "publication": {
            "publication_status": publication_result.get("publication_status"),
            "published_chunk_count": publication_result.get("published_chunk_count"),
        },
        "runtime": {
            "knowledge_index_runtime_version": KNOWLEDGE_INDEX_RUNTIME_VERSION,
            "embeddings_indexed": False,
            "qdrant_indexed": False,
            "postgres_fts_indexed": False,
            "ai_required": False,
        },
    }


def _metadata_entries(
    publication_result: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    publication_evidence_id: uuid.UUID,
) -> dict[str, dict[str, Any]]:
    metadata = _document_metadata(publication_result, chunks, publication_evidence_id=publication_evidence_id)
    return {
        "lineage": metadata["lineage"],
        "hashes": metadata["hashes"],
        "publication": metadata["publication"],
        "processing": {
            "processing_session_id": publication_result.get("processing_session_id"),
            "chunk_session_id": publication_result.get("chunk_session_id"),
        },
        "runtime_versions": metadata["runtime"],
    }


def _document_to_dict(document: Any) -> dict[str, Any]:
    return {
        "knowledge_document_id": str(document.id),
        "artifact_id": document.artifact_id,
        "document_record_id": document.document_record_id,
        "document_version_id": document.document_version_id,
        "publication_id": document.publication_id,
        "status": document.status,
        "version": document.version,
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
        "text": chunk.text,
        "content_hash": chunk.content_hash,
        "semantic_hash": chunk.semantic_hash,
        "content_type": chunk.content_type,
        "chunk_scope": chunk.chunk_scope,
        "status": chunk.status,
        "metadata": chunk.metadata_json or {},
    }


def _metadata_to_dict(item: Any) -> dict[str, Any]:
    return {
        "knowledge_metadata_id": str(item.id),
        "knowledge_document_id": str(item.knowledge_document_id),
        "metadata_key": item.metadata_key,
        "metadata_value": item.metadata_value or {},
    }


def serialize_knowledge_index_result(result: KnowledgeIndexResult) -> dict[str, Any]:
    return {
        "knowledge_index_runtime_schema_version": KNOWLEDGE_INDEX_RUNTIME_SCHEMA_VERSION,
        "index_status": result.index_status,
        "index_completed": result.index_completed,
        "index_succeeded": result.index_succeeded,
        "document_indexed": result.knowledge_document is not None,
        "chunks_indexed": result.chunks_indexed,
        "chunks_created": result.chunks_created,
        "chunks_updated": result.chunks_updated,
        "chunks_superseded": result.chunks_superseded,
        "metadata_persisted": bool(result.knowledge_metadata),
        "idempotent": result.idempotent,
        "reindex_performed": result.reindex_performed,
        "knowledge_document": result.knowledge_document,
        "knowledge_chunks": list(result.knowledge_chunks),
        "knowledge_metadata": list(result.knowledge_metadata),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "persistence_status": "persisted" if result.index_succeeded else "not_persisted",
        "embeddings_indexed": False,
        "qdrant_indexed": False,
        "postgres_fts_indexed": False,
        "ai_required": False,
    }


def _lineage_issue(message: str, *, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": "RESOURCE_LINEAGE_INCOMPLETE",
        "severity": "blocking",
        "component": "knowledge_lineage",
        "item_id": item_id,
        "message": message,
    }


def validate_publication_lineage(
    db: Session,
    publication_result: dict[str, Any],
    *,
    artifact: Artifact | None = None,
) -> list[dict[str, Any]]:
    document_record_id = publication_result.get("document_record_id")
    document_version_id = publication_result.get("document_version_id")
    issues: list[dict[str, Any]] = []
    if not document_record_id:
        issues.append(_lineage_issue("Knowledge indexing requires publication_result.document_record_id."))
    if not document_version_id:
        issues.append(_lineage_issue("Knowledge indexing requires publication_result.document_version_id."))
    if issues:
        return issues
    try:
        record_uuid = uuid.UUID(str(document_record_id))
        version_uuid = uuid.UUID(str(document_version_id))
    except (TypeError, ValueError):
        return [_lineage_issue("Knowledge indexing received invalid document lineage identifiers.")]
    record = db.get(DocumentRecord, record_uuid)
    version = db.get(DocumentVersion, version_uuid)
    if record is None:
        issues.append(_lineage_issue("Knowledge indexing document_record_id does not exist.", item_id=str(record_uuid)))
    if version is None:
        issues.append(
            _lineage_issue("Knowledge indexing document_version_id does not exist.", item_id=str(version_uuid))
        )
    if record is not None and version is not None and version.document_record_id != record.id:
        issues.append(
            _lineage_issue(
                "Knowledge indexing document_version_id does not belong to document_record_id.",
                item_id=str(version_uuid),
            )
        )
    if record is not None and version is not None and version.organization_id != record.organization_id:
        issues.append(
            _lineage_issue(
                "Knowledge indexing document lineage crosses organization scope.",
                item_id=str(version_uuid),
            )
        )
    if artifact is not None:
        if str(publication_result.get("artifact_id") or "") != str(artifact.id):
            issues.append(_lineage_issue("Knowledge publication artifact_id does not match persisted artifact."))
        if str(record_uuid) != str(artifact.document_record_id):
            issues.append(_lineage_issue("Knowledge publication document_record_id does not match artifact."))
        if str(version_uuid) != str(artifact.document_version_id):
            issues.append(_lineage_issue("Knowledge publication document_version_id does not match artifact."))
        if record is not None and record.organization_id != artifact.organization_id:
            issues.append(_lineage_issue("Knowledge publication document crosses artifact organization scope."))
        if version is not None and version.organization_id != artifact.organization_id:
            issues.append(_lineage_issue("Knowledge publication version crosses artifact organization scope."))
    return issues


def _persist_publication_evidence(
    db: Session,
    *,
    publication_result: dict[str, Any],
    organization_id: uuid.UUID,
) -> tuple[dict[str, Any], uuid.UUID | None]:
    persisted_payload = dict(publication_result)
    persisted_payload["organization_id"] = str(organization_id)
    execution_id = str(
        persisted_payload.get("processing_session_id")
        or persisted_payload.get("publication_id")
        or f"knowledge-publication:{persisted_payload.get('artifact_id')}"
    )
    persistence = persist_runtime_outputs(
        db,
        execution_id=execution_id,
        artifact_id=str(persisted_payload.get("artifact_id")) if persisted_payload.get("artifact_id") else None,
        runtime_outputs={"knowledge_publication": persisted_payload},
    )
    for record in persistence.get("persisted_records") or []:
        if (
            record.get("runtime_domain") == "knowledge_publication"
            and record.get("record_type") == "publication_result"
        ):
            try:
                return persistence, uuid.UUID(str(record.get("id")))
            except (TypeError, ValueError):
                return persistence, None
    return persistence, None


def _publication_gate_issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "knowledge_publication_evidence",
        "item_id": None,
        "message": message,
    }


def _blocked_index(
    blocking_issues: list[dict[str, Any]],
    *,
    gateway: dict[str, Any] | None = None,
    publication_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = KnowledgeIndexResult(
        index_status="blocked",
        index_completed=False,
        index_succeeded=False,
        knowledge_document=None,
        blocking_issues=blocking_issues,
        warnings=list(gateway.get("warnings") or []) if gateway is not None else [],
    )
    payload = serialize_knowledge_index_result(result)
    if gateway is not None:
        payload["knowledge_index_gateway"] = gateway
    if publication_gate is not None:
        payload["knowledge_publication_evidence_gate"] = publication_gate
    return payload


def _persisted_publication_lineage_issues(
    db: Session,
    *,
    evidence: KnowledgePublicationEvidenceV1,
    record: RuntimePersistenceRecord,
    artifact: Artifact,
    publication_result: dict[str, Any],
) -> list[dict[str, Any]]:
    issues = validate_publication_lineage(db, publication_result, artifact=artifact)
    if evidence.organization_id != artifact.organization_id:
        issues.append(_lineage_issue("Knowledge publication evidence crosses organization scope."))
    if evidence.processing_session_id != publication_result.get("processing_session_id"):
        issues.append(_lineage_issue("Knowledge publication processing session lineage is inconsistent."))
    publication_id = evidence.publication_id
    if not publication_id:
        issues.append(_lineage_issue("Knowledge publication evidence requires publication_id."))
    elif record.record_key != publication_id:
        issues.append(_lineage_issue("Knowledge publication record key does not match publication_id."))
    chunks = publication_result.get("published_chunks")
    if not isinstance(chunks, list) or len(chunks) != evidence.published_chunk_count:
        issues.append(_lineage_issue("Knowledge publication chunk count does not match persisted chunks."))
        return issues
    seen_chunk_ids: set[str] = set()
    for position, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("published_chunk_id") or "")
        if chunk_id in seen_chunk_ids:
            issues.append(_lineage_issue("Persisted publication has duplicate chunk identity.", item_id=str(position)))
        seen_chunk_ids.add(chunk_id)
        if chunk.get("chunk_index") != position:
            issues.append(_lineage_issue("Persisted publication chunk order is inconsistent.", item_id=str(position)))
        expected = (
            ("artifact_id", artifact.id),
            ("publication_id", publication_id),
            ("document_record_id", artifact.document_record_id),
            ("document_version_id", artifact.document_version_id),
        )
        if any(str(chunk.get(key) or "") != str(value) for key, value in expected):
            issues.append(
                _lineage_issue(
                    "Published chunk does not match persisted artifact and publication lineage.",
                    item_id=str(position),
                )
            )
    return issues


def build_knowledge_index_from_publication_evidence(
    db: Session,
    *,
    evidence_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    """Index only the publication payload reloaded from scoped PostgreSQL evidence."""

    try:
        scoped_evidence = read_knowledge_publication_evidence_v1(
            db, organization_id=organization_id, evidence_id=evidence_id
        )
    except ValueError:
        return _blocked_index(
            [
                _publication_gate_issue(
                    "knowledge_publication_evidence_invalid", "Persisted publication evidence is invalid."
                )
            ]
        )
    if scoped_evidence is None:
        return _blocked_index(
            [
                _publication_gate_issue(
                    "knowledge_publication_evidence_missing", "Persisted publication evidence is unavailable."
                )
            ]
        )
    try:
        artifact_uuid = uuid.UUID(str(scoped_evidence.artifact_id))
    except (TypeError, ValueError):
        return _blocked_index([_lineage_issue("Persisted publication artifact_id is invalid.")])
    artifact = db.get(Artifact, artifact_uuid)
    if artifact is None or artifact.organization_id != organization_id:
        return _blocked_index(
            [
                _publication_gate_issue(
                    "knowledge_publication_evidence_missing", "Persisted publication evidence is unavailable."
                )
            ]
        )

    try:
        publication_gate = evaluate_knowledge_publication_index_gate_v1(
            db,
            organization_id=organization_id,
            evidence_id=evidence_id,
            artifact_id=str(artifact.id),
        )
    except ValueError:
        return _blocked_index(
            [
                _publication_gate_issue(
                    "knowledge_publication_evidence_invalid", "Persisted publication evidence is invalid."
                )
            ]
        )
    publication_gate_payload = serialize_knowledge_publication_index_gate_v1(publication_gate)
    if not publication_gate.ready or publication_gate.publication_evidence is None:
        return _blocked_index(
            list(publication_gate.blocking_issues)
            or [
                _publication_gate_issue(
                    "knowledge_publication_evidence_missing", "Persisted publication evidence is unavailable."
                )
            ],
            publication_gate=publication_gate_payload,
        )

    evidence = publication_gate.publication_evidence
    record = db.get(RuntimePersistenceRecord, evidence_id)
    if record is None or record.runtime_domain != "knowledge_publication" or record.record_type != "publication_result":
        return _blocked_index(
            [
                _publication_gate_issue(
                    "knowledge_publication_evidence_missing", "Persisted publication evidence is unavailable."
                )
            ]
        )
    publication_result = dict(evidence.payload)
    gateway = build_knowledge_index_gateway(publication_result)
    lineage_issues = _persisted_publication_lineage_issues(
        db,
        evidence=evidence,
        record=record,
        artifact=artifact,
        publication_result=publication_result,
    )
    if gateway.get("blocking_issues") or lineage_issues:
        return _blocked_index(
            list(gateway.get("blocking_issues") or []) + lineage_issues,
            gateway=gateway,
            publication_gate=publication_gate_payload,
        )

    chunks = publication_result["published_chunks"]
    artifact_id = str(artifact.id)
    publication_id = str(evidence.publication_id)
    signature = _content_signature(chunks)
    repository = KnowledgeIndexRepository(db)
    document, document_created, document_changed = repository.upsert_document(
        artifact_id=artifact_id,
        publication_id=publication_id,
        content_signature=signature,
        document_record_id=publication_result.get("document_record_id"),
        document_version_id=publication_result.get("document_version_id"),
        metadata=_document_metadata(publication_result, chunks, publication_evidence_id=evidence_id),
    )
    chunks_created = 0
    chunks_updated = 0
    indexed_chunks = []
    for chunk in chunks:
        indexed, created, changed = repository.upsert_chunk(
            knowledge_document_id=document.id,
            publication_id=publication_id,
            artifact_id=artifact_id,
            chunk=chunk,
        )
        chunks_created += 1 if created else 0
        chunks_updated += 1 if (not created and changed) else 0
        indexed_chunks.append(_chunk_to_dict(indexed))
    superseded = repository.mark_missing_chunks_superseded(
        knowledge_document_id=document.id,
        active_published_chunk_ids=[str(chunk.get("published_chunk_id")) for chunk in chunks],
    )
    metadata = [
        _metadata_to_dict(
            repository.upsert_metadata(knowledge_document_id=document.id, metadata_key=key, metadata_value=value)
        )
        for key, value in _metadata_entries(publication_result, chunks, publication_evidence_id=evidence_id).items()
    ]
    db.commit()
    idempotent = (
        not document_created
        and not document_changed
        and chunks_created == 0
        and chunks_updated == 0
        and superseded == 0
    )
    result = KnowledgeIndexResult(
        index_status="completed",
        index_completed=True,
        index_succeeded=True,
        knowledge_document=_document_to_dict(document),
        knowledge_chunks=indexed_chunks,
        knowledge_metadata=metadata,
        chunks_indexed=len(indexed_chunks),
        chunks_created=chunks_created,
        chunks_updated=chunks_updated,
        chunks_superseded=superseded,
        idempotent=idempotent,
        reindex_performed=document_changed or chunks_updated > 0 or superseded > 0,
        warnings=gateway.get("warnings") or [],
    )
    return {
        **serialize_knowledge_index_result(result),
        "knowledge_index_gateway": gateway,
        "knowledge_publication_evidence_gate": publication_gate_payload,
    }


def build_knowledge_index(
    db: Session,
    publication_result: dict[str, Any],
    *,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Adapt the legacy payload to persisted evidence before indexing."""

    gateway = build_knowledge_index_gateway(publication_result)
    artifact_id = publication_result.get("artifact_id")
    try:
        artifact_uuid = uuid.UUID(str(artifact_id))
    except (TypeError, ValueError):
        return _blocked_index(
            list(gateway.get("blocking_issues") or [])
            + [_lineage_issue("Knowledge indexing requires a valid persisted artifact_id.")],
            gateway=gateway,
        )
    artifact = db.get(Artifact, artifact_uuid)
    if artifact is None or (organization_id is not None and artifact.organization_id != organization_id):
        return _blocked_index(
            list(gateway.get("blocking_issues") or [])
            + [_lineage_issue("Knowledge indexing artifact is unavailable in the organization scope.")],
            gateway=gateway,
        )
    lineage_issues = validate_publication_lineage(db, publication_result, artifact=artifact)
    if gateway.get("blocking_issues") or lineage_issues:
        return _blocked_index(list(gateway.get("blocking_issues") or []) + lineage_issues, gateway=gateway)

    publication_persistence, evidence_id = _persist_publication_evidence(
        db,
        publication_result=publication_result,
        organization_id=artifact.organization_id,
    )
    if evidence_id is None:
        return {
            **_blocked_index(
                [
                    _publication_gate_issue(
                        "knowledge_publication_evidence_persistence_missing",
                        "Knowledge Index requires persisted Knowledge Publication evidence before indexing.",
                    )
                ],
                gateway=gateway,
            ),
            "publication_runtime_persistence": publication_persistence,
        }
    return {
        **build_knowledge_index_from_publication_evidence(
            db,
            evidence_id=evidence_id,
            organization_id=artifact.organization_id,
        ),
        "publication_runtime_persistence": publication_persistence,
    }


def read_knowledge_document(db: Session, document_id: str) -> dict[str, Any] | None:
    repository = KnowledgeIndexRepository(db)
    try:
        document_uuid = uuid.UUID(document_id)
    except (TypeError, ValueError):
        return None
    document = repository.get_document(document_uuid)
    if document is None:
        return None
    payload = _document_to_dict(document)
    payload["chunks"] = [_chunk_to_dict(chunk) for chunk in repository.list_chunks_for_document(document.id)]
    payload["knowledge_metadata"] = [
        _metadata_to_dict(item) for item in repository.list_metadata_for_document(document.id)
    ]
    return payload


def read_knowledge_chunk(db: Session, chunk_id: str) -> dict[str, Any] | None:
    try:
        chunk_uuid = uuid.UUID(chunk_id)
    except (TypeError, ValueError):
        return None
    chunk = KnowledgeIndexRepository(db).get_chunk(chunk_uuid)
    return _chunk_to_dict(chunk) if chunk is not None else None
