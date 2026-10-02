"""Derived Vector Index Runtime foundation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_index import VectorIndexRecord
from app.repositories.vector_index import VectorIndexRepository
from app.services.qdrant_provider_contracts import QdrantProviderDescriptor
from app.services.qdrant_provider_runtime import get_qdrant_provider_runtime_adapter
from app.services.vector_index_gateway import build_vector_index_gateway, build_vector_index_health

VECTOR_INDEX_RUNTIME_SCHEMA_VERSION = "1"
VECTOR_INDEX_STATUS_BLOCKED = "blocked"
VECTOR_INDEX_STATUS_COMPLETED = "completed"


@dataclass(frozen=True)
class VectorIndexRuntimeResult:
    vector_index_status: str
    vector_index_prepared: bool
    vector_index_record_created: bool
    vector_index_metadata_persisted: bool
    vector_index_record: dict[str, Any] | None
    vector_index_gateway: dict[str, Any]
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def vector_index_record_to_dict(record: VectorIndexRecord) -> dict[str, Any]:
    return {
        "vector_index_id": str(record.vector_index_id),
        "embedding_id": str(record.embedding_id),
        "knowledge_chunk_id": str(record.knowledge_chunk_id),
        "knowledge_document_id": str(record.knowledge_document_id),
        "index_name": record.index_name,
        "index_provider": record.index_provider,
        "index_provider_type": record.index_provider_type,
        "index_status": record.index_status,
        "index_version": record.index_version,
        "vector_dimensions": record.vector_dimensions,
        "vector_hash": record.vector_hash,
        "external_index_id": record.external_index_id,
        "external_point_id": record.external_point_id,
        "indexed_at": record.indexed_at.isoformat() if record.indexed_at else None,
        "failed_at": record.failed_at.isoformat() if record.failed_at else None,
        "failure_reason": record.failure_reason,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def serialize_vector_index_runtime_result(result: VectorIndexRuntimeResult) -> dict[str, Any]:
    completed = result.vector_index_status == VECTOR_INDEX_STATUS_COMPLETED
    return {
        "vector_index_runtime_schema_version": VECTOR_INDEX_RUNTIME_SCHEMA_VERSION,
        "vector_index_status": result.vector_index_status,
        "vector_index_prepared": result.vector_index_prepared,
        "vector_index_completed": completed,
        "vector_index_succeeded": completed,
        "vector_index_record_created": result.vector_index_record_created,
        "vector_index_metadata_persisted": result.vector_index_metadata_persisted,
        "vector_values_stored": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "semantic_search_enabled": False,
        "hybrid_search_enabled": False,
        "postgresql_source_of_truth": True,
        "vector_index_record": result.vector_index_record,
        "vector_index_gateway": result.vector_index_gateway,
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "persistence_status": "persisted" if completed else "not_persisted",
    }


def _metadata_execution(gateway: dict[str, Any]) -> dict[str, Any]:
    session = gateway.get("vector_index_session") if isinstance(gateway.get("vector_index_session"), dict) else {}
    embedding = gateway.get("embedding_record") if isinstance(gateway.get("embedding_record"), dict) else {}
    chunk = gateway.get("knowledge_chunk") if isinstance(gateway.get("knowledge_chunk"), dict) else {}
    qdrant_provider = gateway.get("qdrant_provider") if isinstance(gateway.get("qdrant_provider"), dict) else {}
    qdrant_provider_descriptor = QdrantProviderDescriptor(
        provider_name=qdrant_provider.get("provider_name") or "qdrant-disabled",
        provider_type=qdrant_provider.get("provider_type") or "descriptor-only",
        provider_version=qdrant_provider.get("provider_version") or "descriptor-only/1.0",
        enabled=bool(qdrant_provider.get("enabled")),
        descriptor_only=bool(qdrant_provider.get("descriptor_only", True)),
        endpoint_configured=bool(qdrant_provider.get("endpoint_configured")),
        collection_name=qdrant_provider.get("collection_name")
        or session.get("qdrant_collection_name")
        or "derived-vector-index",
        collection_status=qdrant_provider.get("collection_status") or "disabled",
        vector_dimensions=int(session.get("vector_dimensions") or 0),
        distance_metric=qdrant_provider.get("distance_metric") or "cosine",
    )
    qdrant_adapter = get_qdrant_provider_runtime_adapter()
    qdrant_execution_plan = qdrant_adapter.build_execution_plan(
        qdrant_provider_descriptor,
        collection_name=session.get("qdrant_collection_name"),
        vector_dimensions=int(session.get("vector_dimensions") or 0),
    )
    qdrant_execution_result = qdrant_adapter.execute_vector_index_publication_plan(qdrant_execution_plan)
    return {
        "vector_index_metadata_execution_schema_version": "1",
        "execution_state": "completed" if gateway.get("vector_index_gateway_ready") else "blocked",
        "embedding_id": embedding.get("embedding_id") or session.get("embedding_id"),
        "knowledge_chunk_id": chunk.get("knowledge_chunk_id") or embedding.get("chunk_id"),
        "knowledge_document_id": chunk.get("knowledge_document_id"),
        "index_name": session.get("index_name"),
        "index_provider": session.get("index_provider"),
        "index_provider_type": session.get("index_provider_type"),
        "index_version": session.get("index_version"),
        "vector_dimensions": session.get("vector_dimensions"),
        "vector_hash": embedding.get("embedding_hash"),
        "runtime_metadata": {
            **(session.get("runtime_metadata") if isinstance(session.get("runtime_metadata"), dict) else {}),
            "embedding_record": embedding,
            "knowledge_chunk": chunk,
            "external_index_descriptor": {
                "provider": session.get("index_provider"),
                "provider_type": session.get("index_provider_type"),
                "enabled": False,
                "authoritative": False,
            },
            "qdrant_provider_name": qdrant_provider_descriptor.provider_name,
            "qdrant_provider_type": qdrant_provider_descriptor.provider_type,
            "qdrant_enabled": qdrant_provider_descriptor.enabled,
            "qdrant_descriptor_only": qdrant_provider_descriptor.descriptor_only,
            "qdrant_collection_name": session.get("qdrant_collection_name")
            or qdrant_provider_descriptor.collection_name,
            "qdrant_execution_plan": qdrant_execution_plan.as_dict(),
            "qdrant_execution_result": qdrant_execution_result.as_dict(),
            "vector_values_stored": False,
            "qdrant_called": False,
            "network_call_attempted": False,
            "semantic_search_enabled": False,
            "hybrid_search_enabled": False,
            "postgresql_source_of_truth": True,
        },
    }


def _persist_vector_index_record(db: Session, metadata_execution: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    if metadata_execution.get("execution_state") != "completed":
        return None, False
    repository = VectorIndexRepository(db)
    record, created = repository.create_vector_index_record(
        embedding_id=uuid.UUID(str(metadata_execution.get("embedding_id"))),
        knowledge_chunk_id=uuid.UUID(str(metadata_execution.get("knowledge_chunk_id"))),
        knowledge_document_id=uuid.UUID(str(metadata_execution.get("knowledge_document_id"))),
        index_name=str(metadata_execution.get("index_name")),
        index_provider=str(metadata_execution.get("index_provider")),
        index_provider_type=str(metadata_execution.get("index_provider_type")),
        index_version=str(metadata_execution.get("index_version")),
        vector_dimensions=int(metadata_execution.get("vector_dimensions") or 0),
        vector_hash=metadata_execution.get("vector_hash"),
        runtime_metadata=metadata_execution.get("runtime_metadata")
        if isinstance(metadata_execution.get("runtime_metadata"), dict)
        else {},
    )
    prepared = repository.mark_vector_index_prepared(
        record.vector_index_id,
        runtime_metadata={"metadata_persisted": True, "vector_index_metadata_persisted": True},
    )
    db.commit()
    return vector_index_record_to_dict(prepared or record), created


def build_vector_index_runtime(
    db: Session,
    *,
    embedding_id: str,
    index_name: str | None = None,
    index_provider: str | None = None,
    index_provider_type: str | None = None,
    index_version: str | None = None,
    qdrant_provider_name: str | None = None,
    qdrant_collection_name: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_vector_index_gateway(
        db,
        embedding_id=embedding_id,
        index_name=index_name,
        index_provider=index_provider,
        index_provider_type=index_provider_type,
        index_version=index_version,
        qdrant_provider_name=qdrant_provider_name,
        qdrant_collection_name=qdrant_collection_name,
        runtime_metadata=runtime_metadata,
    )
    if gateway.get("blocking_issues"):
        result = VectorIndexRuntimeResult(
            vector_index_status=VECTOR_INDEX_STATUS_BLOCKED,
            vector_index_prepared=False,
            vector_index_record_created=False,
            vector_index_metadata_persisted=False,
            vector_index_record=None,
            vector_index_gateway=gateway,
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=gateway.get("warnings") or [],
            next_available_actions=gateway.get("next_available_actions") or [],
        )
        return serialize_vector_index_runtime_result(result)

    metadata_execution = _metadata_execution(gateway)
    record, created = _persist_vector_index_record(db, metadata_execution)
    result = VectorIndexRuntimeResult(
        vector_index_status=VECTOR_INDEX_STATUS_COMPLETED,
        vector_index_prepared=True,
        vector_index_record_created=bool(record) and created,
        vector_index_metadata_persisted=bool(record),
        vector_index_record=record,
        vector_index_gateway=gateway,
        warnings=gateway.get("warnings") or [],
        next_available_actions=[
            {
                "action": "inspect_vector_index_record",
                "available": bool(record),
                "status": "ready" if record else "blocked",
            }
        ],
    )
    payload = {**serialize_vector_index_runtime_result(result), "vector_index_metadata_execution": metadata_execution}
    runtime_metadata_payload = (record.get("runtime_metadata") if isinstance(record, dict) else {}) or {}
    payload = {
        **payload,
        "qdrant_provider_name": runtime_metadata_payload.get("qdrant_provider_name"),
        "qdrant_provider_type": runtime_metadata_payload.get("qdrant_provider_type"),
        "qdrant_enabled": bool(runtime_metadata_payload.get("qdrant_enabled")),
        "qdrant_descriptor_only": bool(runtime_metadata_payload.get("qdrant_descriptor_only", True)),
        "qdrant_collection_name": runtime_metadata_payload.get("qdrant_collection_name"),
        "network_call_attempted": False,
    }
    if persist_snapshot and record:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"vector-index-runtime:{record['vector_index_id']}",
            artifact_id=((record.get("runtime_metadata") or {}).get("knowledge_chunk") or {}).get("artifact_id"),
            runtime_outputs={"vector_index_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_vector_index_record(db: Session, vector_index_id: str) -> dict[str, Any] | None:
    try:
        record_uuid = uuid.UUID(str(vector_index_id))
    except (TypeError, ValueError):
        return None
    record = VectorIndexRepository(db).get_vector_index_record(record_uuid)
    return vector_index_record_to_dict(record) if record is not None else None


__all__ = [
    "build_vector_index_runtime",
    "build_vector_index_health",
    "read_vector_index_record",
    "vector_index_record_to_dict",
]
