"""Control plane for document processing sessions and runtime execution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.document_binary_upload_control_plane import build_upload_session_status
from app.services.document_processing_handoff import build_document_processing_handoff
from app.services.document_processing_runtime import (
    build_document_processing_and_chunk_execution,
    build_document_processing_chunk_and_publication_execution,
    build_document_processing_execution,
    build_document_processing_publication_and_search_execution,
)
from app.services.processing_publication_gate import (
    evaluate_processing_publication_gate_v1,
    serialize_processing_publication_gate_v1,
)
from app.services.runtime_persistence_runtime import persist_runtime_outputs
from app.services.storage_execution_control_plane import build_storage_execution_status

PROCESSING_RUNTIME_EXECUTION_TYPE = "document.indexing"
PROCESSING_EVIDENCE_PIPELINE_REVISION = "document-processing-runtime/v1"


def _blocked_publication_result(gate_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "publication_status": "blocked",
        "publication_completed": False,
        "publication_succeeded": False,
        "knowledge_published": False,
        "published_chunk_count": 0,
        "published_chunks": [],
        "blocking_issues": list(gate_payload.get("blocking_issues") or []),
        "warnings": [],
        "next_available_actions": [
            {
                "action": "publish_to_knowledge",
                "available": False,
                "status": "blocked",
                "reason": "processing_evidence_gate_blocked",
            }
        ],
        "processing_evidence_gate": gate_payload,
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def _blocked_search_result(gate_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "search_status": "blocked",
        "search_completed": False,
        "search_succeeded": False,
        "organization_id": gate_payload.get("organization_id"),
        "result_count": 0,
        "results": [],
        "blocking_issues": list(gate_payload.get("blocking_issues") or []),
        "warnings": [],
        "next_available_actions": [],
        "processing_evidence_gate": gate_payload,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _checksum_value(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.split(":", 1)[1] if value.startswith("sha256:") else value


def _active_processing_runtime_context(
    db: Session,
    *,
    artifact: Artifact,
) -> tuple[RuntimeExecution | None, RuntimeExecutionAttempt | None]:
    execution = db.scalar(
        select(RuntimeExecution)
        .where(
            RuntimeExecution.organization_id == artifact.organization_id,
            RuntimeExecution.execution_type == PROCESSING_RUNTIME_EXECUTION_TYPE,
            RuntimeExecution.subject_type == "document_version",
            RuntimeExecution.subject_id == artifact.document_version_id,
            RuntimeExecution.status.in_(("leased", "running")),
        )
        .order_by(RuntimeExecution.created_at.desc(), RuntimeExecution.id.desc())
        .limit(1)
    )
    if execution is None:
        return None, None
    attempt = db.scalar(
        select(RuntimeExecutionAttempt)
        .where(
            RuntimeExecutionAttempt.organization_id == artifact.organization_id,
            RuntimeExecutionAttempt.execution_id == execution.id,
            RuntimeExecutionAttempt.status.in_(("leased", "running")),
        )
        .order_by(RuntimeExecutionAttempt.attempt_number.desc(), RuntimeExecutionAttempt.id.desc())
        .limit(1)
    )
    return execution, attempt


def _processing_revision_snapshot(revision: ProcessingRevision, *, reused: bool) -> dict[str, Any]:
    return {
        "persistence_status": "persisted",
        "authority": "postgresql",
        "contract": "ProcessingEvidenceV1",
        "processing_revision_id": str(revision.id),
        "organization_id": str(revision.organization_id),
        "document_record_id": str(revision.document_record_id),
        "document_version_id": str(revision.document_version_id),
        "runtime_execution_id": str(revision.runtime_execution_id),
        "runtime_attempt_id": str(revision.runtime_attempt_id),
        "status": revision.status,
        "chunk_count": revision.chunk_count,
        "reused": reused,
    }


def _persist_processing_revision_evidence(
    db: Session,
    *,
    artifact_id: uuid.UUID,
    processing_chunk_response: dict[str, Any],
    chunker_config: dict[str, Any] | None,
) -> dict[str, Any]:
    chunk_count = _int_value(processing_chunk_response.get("chunk_count"))
    processing_completed = processing_chunk_response.get("processing_completed") is True
    processing_succeeded = processing_chunk_response.get("processing_succeeded") is True
    chunks_created = processing_chunk_response.get("chunks_created") is True
    if not (processing_completed and processing_succeeded and chunks_created and chunk_count > 0):
        return {
            "persistence_status": "skipped",
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "reason": "processing_and_chunk_completion_required",
        }

    artifact = db.get(Artifact, artifact_id)
    if (
        artifact is None
        or artifact.organization_id is None
        or artifact.document_record_id is None
        or artifact.document_version_id is None
    ):
        return {
            "persistence_status": "skipped",
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "reason": "artifact_lineage_required",
        }

    runtime_execution, runtime_attempt = _active_processing_runtime_context(db, artifact=artifact)
    if runtime_execution is None or runtime_attempt is None:
        return {
            "persistence_status": "skipped",
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "reason": "active_runtime_attempt_required",
        }

    existing = db.scalar(
        select(ProcessingRevision).where(
            ProcessingRevision.organization_id == artifact.organization_id,
            ProcessingRevision.runtime_execution_id == runtime_execution.id,
            ProcessingRevision.runtime_attempt_id == runtime_attempt.id,
        )
    )
    if existing is not None:
        return _processing_revision_snapshot(existing, reused=True)

    processing_execution = processing_chunk_response.get("processing_execution")
    processing_execution = processing_execution if isinstance(processing_execution, dict) else {}
    processing_result = processing_chunk_response.get("processing_result")
    processing_result = processing_result if isinstance(processing_result, dict) else {}
    parser_runtime = processing_execution.get("parser_runtime")
    parser_runtime = parser_runtime if isinstance(parser_runtime, dict) else {}
    chunk_generation = processing_chunk_response.get("chunk_generation")
    chunk_generation = chunk_generation if isinstance(chunk_generation, dict) else {}

    started_at = (
        runtime_attempt.started_at
        or runtime_attempt.leased_at
        or runtime_execution.started_at
        or runtime_execution.requested_at
        or datetime.now(UTC)
    )
    source_checksum = _checksum_value(
        processing_result.get("content_sha256") or processing_result.get("source_checksum")
    )
    content_unit_count = max(
        1,
        _int_value(processing_result.get("paragraph_count"))
        or _int_value(processing_result.get("line_count")),
    )
    revision = ProcessingRevision(
        organization_id=artifact.organization_id,
        document_record_id=artifact.document_record_id,
        document_version_id=artifact.document_version_id,
        runtime_execution_id=runtime_execution.id,
        runtime_attempt_id=runtime_attempt.id,
        pipeline_profile_id=None,
        pipeline_profile_revision=PROCESSING_EVIDENCE_PIPELINE_REVISION,
        adapter_key=str(parser_runtime.get("parser_name") or processing_result.get("parser_name") or "text/plain"),
        adapter_version=str(
            parser_runtime.get("parser_version") or processing_result.get("parser_version") or "runtime/v1"
        ),
        configuration_snapshot={
            "artifact_id": str(artifact.id),
            "chunker_config": dict(chunker_config or {}),
            "processing_runtime_schema_version": processing_execution.get("processing_runtime_schema_version"),
            "chunk_generation_schema_version": chunk_generation.get("chunk_generation_schema_version"),
            "ai_required": False,
        },
        source_checksum_sha256=source_checksum,
        status="completed",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        content_unit_count=content_unit_count,
        chunk_count=chunk_count,
        manifest_artifact_id=None,
        created_by=runtime_execution.requested_by,
        updated_by=runtime_execution.requested_by,
    )
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_race = db.scalar(
            select(ProcessingRevision).where(
                ProcessingRevision.organization_id == artifact.organization_id,
                ProcessingRevision.runtime_execution_id == runtime_execution.id,
                ProcessingRevision.runtime_attempt_id == runtime_attempt.id,
            )
        )
        if existing_after_race is None:
            raise
        return _processing_revision_snapshot(existing_after_race, reused=True)
    db.refresh(revision)
    return _processing_revision_snapshot(revision, reused=False)


def build_document_processing_status(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None

    upload_session = upload_status["upload_session"]
    processing_session = upload_status["processing_session"]
    storage_execution_status = build_storage_execution_status(db, artifact_id=artifact_id) or {}
    processing_handoff = build_document_processing_handoff(
        artifact_id=str(artifact_id),
        storage_execution_status=storage_execution_status,
    )
    return {
        "artifact_id": str(artifact_id),
        "upload_session_id": upload_session.get("upload_session_id"),
        "processing_session_id": processing_session["processing_session_id"],
        "document_record_id": processing_session["document_record_id"],
        "document_version_id": processing_session["document_version_id"],
        "processing_state": processing_session["processing_state"],
        "processing_session": processing_session,
        "processing_plan": processing_session["processing_plan"],
        "execution_flags": processing_session["execution_flags"],
        "processing_capabilities": processing_session["processing_capabilities"],
        "pending_operations": processing_session["pending_operations"],
        "blocking_issues": processing_session["blocking_issues"],
        "warnings": processing_session["warnings"],
        "next_available_actions": processing_session["next_available_actions"],
        "processing_handoff_supported": True,
        "processing_handoff_ready": bool(processing_handoff.get("processing_handoff_ready")),
        "processing_handoff_allowed": bool(processing_handoff.get("processing_handoff_allowed")),
        "processing_handoff_status": processing_handoff.get("handoff_status"),
        "processing_handoff_blocking_issues": processing_handoff.get("handoff_blocking_issues") or [],
        "processing_handoff_warnings": processing_handoff.get("handoff_warnings") or [],
        "source_storage_summary": processing_handoff.get("source_storage_summary") or {},
        "next_processing_actions": processing_handoff.get("next_processing_actions") or [],
        "processing_handoff": processing_handoff,
        "processing_runtime_supported": True,
        "processing_runtime_endpoint": f"/api/documents/processing/{artifact_id}/execute",
        "chunk_runtime_supported": True,
        "chunk_runtime_endpoint": f"/api/documents/processing/{artifact_id}/chunks/generate",
        "knowledge_publication_runtime_supported": True,
        "knowledge_publication_runtime_endpoint": f"/api/documents/processing/{artifact_id}/knowledge/publish",
        "enterprise_search_runtime_supported": True,
        "enterprise_search_runtime_endpoint": f"/api/documents/processing/{artifact_id}/search",
        "upload_session": upload_session,
        "upload_session_validation": upload_status.get("session_validation"),
        "upload_control_capabilities": upload_status.get("control_capabilities"),
    }


def build_document_processing_handoff_prepare(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    storage_execution_status = build_storage_execution_status(db, artifact_id=artifact_id)
    if storage_execution_status is None:
        return None
    return build_document_processing_handoff(
        artifact_id=str(artifact_id),
        storage_execution_status=storage_execution_status,
    )


def build_document_processing_execute(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    handoff = build_document_processing_handoff_prepare(db, artifact_id=artifact_id)
    if handoff is None:
        return None
    execution = build_document_processing_execution(handoff)
    execution["runtime_persistence"] = persist_runtime_outputs(
        db,
        execution_id=str(execution.get("processing_session_id") or f"processing-runtime:{artifact_id}"),
        artifact_id=str(artifact_id),
        runtime_outputs={"processing": execution},
    )
    return execution


def build_document_processing_chunks_generate(
    db: Session,
    *,
    artifact_id: uuid.UUID,
    storage_execution_status: dict[str, Any] | None = None,
    chunker_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None
    storage_status = storage_execution_status or build_storage_execution_status(db, artifact_id=artifact_id)
    if storage_status is None:
        return None
    handoff = build_document_processing_handoff(
        artifact_id=str(artifact_id),
        storage_execution_status=storage_status,
    )
    execution = build_document_processing_and_chunk_execution(handoff, chunker_config=chunker_config)
    response = {
        **execution,
        "processing_handoff": handoff,
        "storage_verified": bool(storage_status.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "chunk_generation_endpoint": f"/api/documents/processing/{artifact_id}/chunks/generate",
    }
    response["runtime_persistence"] = persist_runtime_outputs(
        db,
        execution_id=str(response.get("processing_session_id") or f"chunk-runtime:{artifact_id}"),
        artifact_id=str(artifact_id),
        runtime_outputs={
            "storage": storage_status,
            "processing": response.get("processing_execution"),
            "chunk": response.get("chunk_generation"),
        },
    )
    response["processing_evidence_persistence"] = _persist_processing_revision_evidence(
        db,
        artifact_id=artifact_id,
        processing_chunk_response=response,
        chunker_config=chunker_config,
    )
    return response


def build_document_processing_knowledge_publish(
    db: Session,
    *,
    artifact_id: uuid.UUID,
    storage_execution_status: dict[str, Any] | None = None,
    chunker_config: dict[str, Any] | None = None,
    publication_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None
    storage_status = storage_execution_status or build_storage_execution_status(db, artifact_id=artifact_id)
    if storage_status is None:
        return None
    handoff = build_document_processing_handoff(
        artifact_id=str(artifact_id),
        storage_execution_status=storage_status,
    )
    gate = evaluate_processing_publication_gate_v1(db, artifact_id=artifact_id)
    gate_payload = serialize_processing_publication_gate_v1(gate)
    processing_session = upload_status.get("processing_session") or {}

    if not gate.ready:
        publication = _blocked_publication_result(gate_payload)
        response = {
            "artifact_id": str(artifact_id),
            "document_record_id": gate_payload.get("document_record_id"),
            "document_version_id": gate_payload.get("document_version_id"),
            "processing_session_id": processing_session.get("processing_session_id"),
            "processing_completed": False,
            "chunk_generation_completed": False,
            "chunks_created": False,
            "chunk_count": 0,
            "publication_completed": False,
            "publication_succeeded": False,
            "knowledge_published": False,
            "published_chunk_count": 0,
            "knowledge_publication": publication,
            "publication_result": publication,
            "processing_evidence_gate": gate_payload,
            "processing_handoff": handoff,
            "storage_verified": bool(storage_status.get("storage_verified")),
            "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
            "knowledge_publication_endpoint": f"/api/documents/processing/{artifact_id}/knowledge/publish",
            "embeddings_created": False,
            "semantic_index_created": False,
            "ai_required": False,
            "persistence_status": "not_persisted",
        }
        response["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=str(response.get("processing_session_id") or f"publication-runtime:{artifact_id}"),
            artifact_id=str(artifact_id),
            runtime_outputs={
                "storage": storage_status,
                "knowledge_publication": publication,
            },
        )
        return response

    execution = build_document_processing_chunk_and_publication_execution(
        handoff,
        chunker_config=chunker_config,
        publication_config=publication_config,
    )
    response = {
        **execution,
        "processing_evidence_gate": gate_payload,
        "processing_handoff": handoff,
        "storage_verified": bool(storage_status.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "knowledge_publication_endpoint": f"/api/documents/processing/{artifact_id}/knowledge/publish",
    }
    publication = response.get("knowledge_publication")
    if isinstance(publication, dict):
        publication["processing_evidence_gate"] = gate_payload
    response["runtime_persistence"] = persist_runtime_outputs(
        db,
        execution_id=str(response.get("processing_session_id") or f"publication-runtime:{artifact_id}"),
        artifact_id=str(artifact_id),
        runtime_outputs={
            "storage": storage_status,
            "processing": response.get("processing_execution"),
            "chunk": response.get("chunk_generation"),
            "knowledge_publication": response.get("knowledge_publication"),
        },
    )
    return response


def build_document_processing_enterprise_search(
    db: Session,
    *,
    artifact_id: uuid.UUID,
    query: str,
    top_k: int | None = None,
    storage_execution_status: dict[str, Any] | None = None,
    chunker_config: dict[str, Any] | None = None,
    publication_config: dict[str, Any] | None = None,
    search_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None
    storage_status = storage_execution_status or build_storage_execution_status(db, artifact_id=artifact_id)
    if storage_status is None:
        return None
    handoff = build_document_processing_handoff(
        artifact_id=str(artifact_id),
        storage_execution_status=storage_status,
    )
    gate = evaluate_processing_publication_gate_v1(db, artifact_id=artifact_id)
    processing_bootstrap: dict[str, Any] | None = None
    if not gate.ready:
        processing_bootstrap = build_document_processing_chunks_generate(
            db,
            artifact_id=artifact_id,
            storage_execution_status=storage_status,
            chunker_config=chunker_config,
        )
        gate = evaluate_processing_publication_gate_v1(db, artifact_id=artifact_id)
    gate_payload = serialize_processing_publication_gate_v1(gate)
    processing_session = upload_status.get("processing_session") or {}

    if not gate.ready:
        publication = _blocked_publication_result(gate_payload)
        enterprise_search = _blocked_search_result(gate_payload)
        response = {
            "artifact_id": str(artifact_id),
            "document_record_id": gate_payload.get("document_record_id"),
            "document_version_id": gate_payload.get("document_version_id"),
            "processing_session_id": processing_session.get("processing_session_id"),
            "processing_completed": False,
            "chunk_generation_completed": False,
            "chunks_created": False,
            "chunk_count": 0,
            "publication_completed": False,
            "publication_succeeded": False,
            "knowledge_published": False,
            "published_chunk_count": 0,
            "knowledge_publication": publication,
            "publication_result": publication,
            "knowledge_index": {},
            "enterprise_search": enterprise_search,
            "processing_evidence_gate": gate_payload,
            "processing_bootstrap": processing_bootstrap,
            "processing_handoff": handoff,
            "storage_verified": bool(storage_status.get("storage_verified")),
            "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
            "enterprise_search_endpoint": f"/api/documents/processing/{artifact_id}/search",
            "embeddings_created": False,
            "semantic_index_created": False,
            "ai_required": False,
            "persistence_status": "not_persisted",
        }
        response["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=str(response.get("processing_session_id") or f"enterprise-search-runtime:{artifact_id}"),
            artifact_id=str(artifact_id),
            runtime_outputs={
                "storage": storage_status,
                "knowledge_publication": publication,
            },
        )
        return response

    execution = build_document_processing_publication_and_search_execution(
        handoff,
        db=db,
        query=query,
        top_k=top_k,
        chunker_config=chunker_config,
        publication_config=publication_config,
        search_config=search_config,
    )
    response = {
        **execution,
        "processing_evidence_gate": gate_payload,
        "processing_bootstrap": processing_bootstrap,
        "processing_handoff": handoff,
        "storage_verified": bool(storage_status.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "enterprise_search_endpoint": f"/api/documents/processing/{artifact_id}/search",
    }
    publication = response.get("knowledge_publication")
    if isinstance(publication, dict):
        publication["processing_evidence_gate"] = gate_payload
    response["runtime_persistence"] = persist_runtime_outputs(
        db,
        execution_id=str(response.get("processing_session_id") or f"enterprise-search-runtime:{artifact_id}"),
        artifact_id=str(artifact_id),
        runtime_outputs={
            "storage": storage_status,
            "processing": response.get("processing_execution"),
            "chunk": response.get("chunk_generation"),
            "knowledge_publication": response.get("knowledge_publication"),
            "knowledge_index": response.get("knowledge_index"),
            "enterprise_search": response.get("enterprise_search"),
        },
    )
    return response
