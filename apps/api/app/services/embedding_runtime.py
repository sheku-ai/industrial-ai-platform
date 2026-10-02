"""Optional Embedding Runtime foundation.

This runtime persists deterministic metadata for embeddings derived from
Knowledge Index chunks. It does not generate vectors or call model providers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge_index import EmbeddingRecord
from app.repositories.embedding import EmbeddingRepository
from app.services.embedding_gateway import build_embedding_gateway
from app.services.embedding_provider_registry import get_embedding_provider_registry
from app.services.embedding_provider_runtime import get_embedding_provider_runtime_adapter

EMBEDDING_RUNTIME_SCHEMA_VERSION = "1"
EMBEDDING_STATUS_BLOCKED = "blocked"
EMBEDDING_STATUS_COMPLETED = "completed"


@dataclass(frozen=True)
class EmbeddingRuntimeResult:
    embedding_status: str
    embedding_runtime_prepared: bool
    embedding_record_created: bool
    embedding_metadata_persisted: bool
    embedding_record: dict[str, Any] | None
    embedding_gateway: dict[str, Any]
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _embedding_record_to_dict(record: EmbeddingRecord) -> dict[str, Any]:
    return {
        "embedding_id": str(record.embedding_id),
        "chunk_id": str(record.chunk_id),
        "model_name": record.model_name,
        "model_version": record.model_version,
        "embedding_dimensions": record.embedding_dimensions,
        "embedding_status": record.embedding_status,
        "embedding_hash": record.embedding_hash,
        "embedding_created_at": record.embedding_created_at.isoformat() if record.embedding_created_at else None,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def serialize_embedding_runtime_result(result: EmbeddingRuntimeResult) -> dict[str, Any]:
    completed = result.embedding_status == EMBEDDING_STATUS_COMPLETED
    return {
        "embedding_runtime_schema_version": EMBEDDING_RUNTIME_SCHEMA_VERSION,
        "embedding_status": result.embedding_status,
        "embedding_runtime_prepared": result.embedding_runtime_prepared,
        "embedding_completed": completed,
        "embedding_succeeded": completed,
        "embedding_record_created": result.embedding_record_created,
        "embedding_metadata_persisted": result.embedding_metadata_persisted,
        "embedding_vector_generated": False,
        "embedding_provider_called": False,
        "semantic_search_used": False,
        "postgresql_source_of_truth": True,
        "embedding_record": result.embedding_record,
        "embedding_gateway": result.embedding_gateway,
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "persistence_status": "persisted" if completed else "not_persisted",
    }


def prepare_embedding(
    db: Session,
    *,
    chunk_id: str,
    model_name: str | None = None,
    model_version: str | None = None,
    embedding_dimensions: int | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_embedding_gateway(
        db,
        chunk_id=chunk_id,
        model_name=model_name,
        model_version=model_version,
        embedding_dimensions=embedding_dimensions,
        runtime_metadata=runtime_metadata,
    )


def execute_embedding_metadata(gateway: dict[str, Any]) -> dict[str, Any]:
    session = gateway.get("embedding_session") if isinstance(gateway.get("embedding_session"), dict) else {}
    chunk = gateway.get("knowledge_chunk") if isinstance(gateway.get("knowledge_chunk"), dict) else {}
    provider_name = (session.get("runtime_metadata") if isinstance(session.get("runtime_metadata"), dict) else {}).get(
        "provider_name"
    ) or "metadata-only"
    provider = get_embedding_provider_registry().resolve(str(provider_name))
    adapter = get_embedding_provider_runtime_adapter()
    provider_request = {
        "chunk_id": session.get("chunk_id"),
        "model_name": session.get("model_name"),
        "model_version": session.get("model_version"),
        "embedding_dimensions": session.get("embedding_dimensions"),
        "knowledge_chunk": chunk,
        "runtime_metadata": session.get("runtime_metadata")
        if isinstance(session.get("runtime_metadata"), dict)
        else {},
    }
    prepare_result = adapter.prepare_embedding(provider=provider, request=provider_request)
    generate_result = adapter.generate_embedding(provider=provider, request=provider_request)
    provider_result = generate_result.get("result") if isinstance(generate_result.get("result"), dict) else {}
    provider_descriptor = provider.describe()
    return {
        "embedding_metadata_execution_schema_version": "1",
        "execution_state": provider_result.get("execution_state")
        if gateway.get("embedding_gateway_ready")
        else "blocked",
        "chunk_id": provider_result.get("chunk_id") or session.get("chunk_id"),
        "model_name": provider_result.get("model_name") or session.get("model_name"),
        "model_version": provider_result.get("model_version") or session.get("model_version"),
        "embedding_dimensions": provider_result.get("embedding_dimensions")
        if provider_result.get("embedding_dimensions") is not None
        else session.get("embedding_dimensions"),
        "embedding_hash": provider_result.get("embedding_hash"),
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "provider_version": provider_descriptor.get("provider_version"),
        "provider_runtime_called": bool(prepare_result.get("provider_runtime_called"))
        and bool(generate_result.get("provider_runtime_called")),
        "provider_generated_vector": bool(provider_result.get("provider_generated_vector")),
        "provider_called": bool(provider_result.get("provider_called")),
        "provider_prepare_result": prepare_result,
        "provider_generate_result": generate_result,
        "runtime_metadata": {
            **(
                provider_result.get("runtime_metadata")
                if isinstance(provider_result.get("runtime_metadata"), dict)
                else {}
            ),
            "provider_descriptor": provider_descriptor,
            "provider_runtime_called": bool(prepare_result.get("provider_runtime_called"))
            and bool(generate_result.get("provider_runtime_called")),
        },
    }


def persist_embedding_record(db: Session, metadata_execution: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    if metadata_execution.get("execution_state") != "completed":
        return None, False
    record, created = EmbeddingRepository(db).create_embedding_record(
        chunk_id=uuid.UUID(str(metadata_execution.get("chunk_id"))),
        model_name=str(metadata_execution.get("model_name")),
        model_version=str(metadata_execution.get("model_version")),
        embedding_dimensions=int(metadata_execution.get("embedding_dimensions") or 0),
        embedding_hash=metadata_execution.get("embedding_hash"),
        runtime_metadata=metadata_execution.get("runtime_metadata")
        if isinstance(metadata_execution.get("runtime_metadata"), dict)
        else {},
    )
    completed = EmbeddingRepository(db).mark_embedding_completed(
        record.embedding_id,
        embedding_hash=str(metadata_execution.get("embedding_hash")),
        runtime_metadata={"metadata_persisted": True},
    )
    db.commit()
    return _embedding_record_to_dict(completed or record), created


def build_embedding_runtime(
    db: Session,
    *,
    chunk_id: str,
    model_name: str | None = None,
    model_version: str | None = None,
    embedding_dimensions: int | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    provider_name: str | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    runtime_metadata = {
        **dict(runtime_metadata or {}),
        "provider_name": provider_name or (runtime_metadata or {}).get("provider_name") or "metadata-only",
    }
    gateway = prepare_embedding(
        db,
        chunk_id=chunk_id,
        model_name=model_name,
        model_version=model_version,
        embedding_dimensions=embedding_dimensions,
        runtime_metadata=runtime_metadata,
    )
    if gateway.get("blocking_issues"):
        result = EmbeddingRuntimeResult(
            embedding_status=EMBEDDING_STATUS_BLOCKED,
            embedding_runtime_prepared=False,
            embedding_record_created=False,
            embedding_metadata_persisted=False,
            embedding_record=None,
            embedding_gateway=gateway,
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=gateway.get("warnings") or [],
            next_available_actions=gateway.get("next_available_actions") or [],
        )
        return serialize_embedding_runtime_result(result)

    metadata_execution = execute_embedding_metadata(gateway)
    record, created = persist_embedding_record(db, metadata_execution)
    result = EmbeddingRuntimeResult(
        embedding_status=EMBEDDING_STATUS_COMPLETED,
        embedding_runtime_prepared=True,
        embedding_record_created=bool(record) and created,
        embedding_metadata_persisted=bool(record),
        embedding_record=record,
        embedding_gateway=gateway,
        warnings=gateway.get("warnings") or [],
        next_available_actions=[
            {
                "action": "inspect_embedding_record",
                "available": bool(record),
                "status": "ready" if record else "blocked",
            }
        ],
    )
    payload = {
        **serialize_embedding_runtime_result(result),
        "embedding_metadata_execution": metadata_execution,
        "provider_registry_loaded": True,
        "metadata_provider_selected": metadata_execution.get("provider_name") == "metadata-only",
        "provider_runtime_called": bool(metadata_execution.get("provider_runtime_called")),
        "provider_name": metadata_execution.get("provider_name"),
        "provider_type": metadata_execution.get("provider_type"),
        "provider_version": metadata_execution.get("provider_version"),
        "provider_generated_vector": bool(metadata_execution.get("provider_generated_vector")),
    }
    if persist_snapshot and record:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"embedding-runtime:{record['embedding_id']}",
            artifact_id=(record.get("runtime_metadata") or {}).get("knowledge_chunk", {}).get("artifact_id"),
            runtime_outputs={"embedding_runtime": payload},
        )
    return payload


def read_embedding_record(db: Session, embedding_id: str) -> dict[str, Any] | None:
    try:
        record_uuid = uuid.UUID(str(embedding_id))
    except (TypeError, ValueError):
        return None
    record = EmbeddingRepository(db).get_embedding(record_uuid)
    return _embedding_record_to_dict(record) if record is not None else None


def build_embedding_health(db: Session) -> dict[str, Any]:
    repository = EmbeddingRepository(db)
    records = repository.list_embeddings(limit=500)
    pending_count = len([record for record in records if record.embedding_status == "pending"])
    completed_count = len([record for record in records if record.embedding_status == "completed"])
    failed_count = len([record for record in records if record.embedding_status == "failed"])
    provider_health = get_embedding_provider_registry().health()
    return {
        "embedding_health_schema_version": "1",
        "embedding_runtime_available": True,
        "embedding_runtime_prepared": True,
        "provider_registry_loaded": bool(provider_health.get("provider_registry_loaded")),
        "registered_provider_count": provider_health.get("registered_provider_count"),
        "embedding_records": len(records),
        "pending_embeddings": pending_count,
        "completed_embeddings": completed_count,
        "failed_embeddings": failed_count,
        "embedding_vector_generated": False,
        "embedding_provider_called": False,
        "semantic_search_used": False,
        "postgresql_source_of_truth": True,
        "qdrant_index_derived": True,
        "persistence_status": "available",
    }
