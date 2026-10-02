"""Document processing session readiness for post-upload pipeline preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROCESSING_SESSION_SCHEMA_VERSION = "1"
PROCESSING_SESSION_STATE_BLOCKED = "blocked"
PROCESSING_SESSION_STATE_PLANNED = "planned"

PROCESSING_STAGE_ORDER = (
    "binary_available",
    "storage_verified",
    "extraction_ready",
    "ocr_ready",
    "parser_ready",
    "chunking_ready",
    "enrichment_ready",
    "embedding_ready",
    "publication_ready",
)

FUTURE_PROCESSING_ACTIONS = (
    "verify_storage",
    "extract_document",
    "execute_ocr",
    "parse_document",
    "generate_chunks",
    "enrich_document",
    "generate_embeddings",
    "publish_to_knowledge",
)

PROCESSING_FALSE_FLAGS = {
    "binary_available": False,
    "storage_verified": False,
    "extraction_executed": False,
    "ocr_executed": False,
    "parser_executed": False,
    "chunks_created": False,
    "enrichment_executed": False,
    "embeddings_created": False,
    "publication_executed": False,
    "ingestion_executed": False,
    "ai_executed": False,
    "workflow_executed": False,
}


@dataclass(frozen=True)
class DocumentProcessingSession:
    processing_session_id: str | None
    artifact_id: str | None
    upload_session_id: str | None
    document_record_id: str | None
    document_version_id: str | None
    processing_state: str
    processing_plan: dict[str, Any] = field(default_factory=dict)
    execution_flags: dict[str, Any] = field(default_factory=dict)
    processing_capabilities: dict[str, Any] = field(default_factory=dict)
    pending_operations: list[dict[str, Any]] = field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _issue(
    code: str,
    message: str,
    *,
    component: str,
    severity: str = "blocking",
    item_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _processing_session_id(*, artifact_id: str | None) -> str | None:
    if not artifact_id:
        return None
    return f"processing-session:{artifact_id}"


def _execution_flags(upload_session: dict[str, Any]) -> dict[str, Any]:
    upload_flags = upload_session.get("execution_flags") or {}
    return {
        **PROCESSING_FALSE_FLAGS,
        "binary_available": bool(upload_flags.get("file_uploaded")),
        "storage_verified": bool(upload_flags.get("object_stored")),
        "chunks_created": bool(upload_flags.get("chunks_created")),
        "embeddings_created": bool(upload_flags.get("embeddings_created")),
        "ingestion_executed": bool(upload_flags.get("ingestion_executed")),
    }


def _stage(
    name: str,
    *,
    status: str,
    required: bool = True,
    dependency: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "stage": name,
        "status": status,
        "required": required,
        "dependency": dependency,
        "reason": reason,
        "executed": False,
    }


def build_processing_plan(upload_session: dict[str, Any]) -> dict[str, Any]:
    upload_flags = upload_session.get("execution_flags") or {}
    runtime_state = upload_session.get("runtime_state")
    binary_available = bool(upload_flags.get("file_uploaded"))
    object_stored = bool(upload_flags.get("object_stored"))
    stages = [
        _stage(
            "binary_available",
            status="planned" if binary_available else "blocked",
            reason=None if binary_available else "binary_content_not_uploaded",
        ),
        _stage(
            "storage_verified",
            status="planned" if object_stored else "blocked",
            dependency="binary_available",
            reason=None if object_stored else "object_not_stored",
        ),
        _stage("extraction_ready", status="blocked", dependency="storage_verified", reason="storage_not_verified"),
        _stage("ocr_ready", status="blocked", dependency="extraction_ready", reason="extraction_not_executed"),
        _stage("parser_ready", status="blocked", dependency="extraction_ready", reason="extraction_not_executed"),
        _stage("chunking_ready", status="blocked", dependency="parser_ready", reason="document_not_parsed"),
        _stage("enrichment_ready", status="blocked", dependency="chunking_ready", reason="chunks_not_created"),
        _stage("embedding_ready", status="blocked", dependency="chunking_ready", reason="chunks_not_created"),
        _stage("publication_ready", status="blocked", dependency="embedding_ready", reason="embeddings_not_created"),
    ]
    return {
        "processing_plan_schema_version": "1",
        "planning_mode": "readiness_only",
        "runtime_state": runtime_state,
        "stages": stages,
        "stage_order": list(PROCESSING_STAGE_ORDER),
        "all_stages_blocked_or_planned": True,
        "real_processing_enabled": False,
        "required_first_step": "upload_binary_content" if not binary_available else "verify_storage",
    }


def build_processing_capabilities(processing_plan: dict[str, Any], upload_session: dict[str, Any]) -> dict[str, Any]:
    upload_flags = upload_session.get("execution_flags") or {}
    storage_ready = bool(upload_flags.get("object_stored"))
    binary_available = bool(upload_flags.get("file_uploaded"))
    return {
        "can_verify_storage": {
            "available": False,
            "status": "blocked",
            "reason": "storage_verification_not_implemented" if binary_available else "binary_content_not_uploaded",
            "future_action": "verify_storage",
        },
        "can_extract_document": {
            "available": False,
            "status": "blocked",
            "reason": "storage_not_verified" if not storage_ready else "extraction_not_implemented",
            "future_action": "extract_document",
        },
        "can_execute_ocr": {
            "available": False,
            "status": "blocked",
            "reason": "extraction_not_executed",
            "future_action": "execute_ocr",
        },
        "can_parse_document": {
            "available": False,
            "status": "blocked",
            "reason": "extraction_not_executed",
            "future_action": "parse_document",
        },
        "can_generate_chunks": {
            "available": False,
            "status": "blocked",
            "reason": "document_not_parsed",
            "future_action": "generate_chunks",
        },
        "can_enrich_document": {
            "available": False,
            "status": "blocked",
            "reason": "chunks_not_created",
            "future_action": "enrich_document",
        },
        "can_generate_embeddings": {
            "available": False,
            "status": "blocked",
            "reason": "chunks_not_created",
            "future_action": "generate_embeddings",
        },
        "can_publish_to_knowledge": {
            "available": False,
            "status": "blocked",
            "reason": "embeddings_not_created",
            "future_action": "publish_to_knowledge",
        },
    }


def build_pending_processing_operations(processing_capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"operation": "verify_storage", **processing_capabilities["can_verify_storage"]},
        {"operation": "extract_document", **processing_capabilities["can_extract_document"]},
        {"operation": "execute_ocr", **processing_capabilities["can_execute_ocr"]},
        {"operation": "parse_document", **processing_capabilities["can_parse_document"]},
        {"operation": "generate_chunks", **processing_capabilities["can_generate_chunks"]},
        {"operation": "enrich_document", **processing_capabilities["can_enrich_document"]},
        {"operation": "generate_embeddings", **processing_capabilities["can_generate_embeddings"]},
        {"operation": "publish_to_knowledge", **processing_capabilities["can_publish_to_knowledge"]},
    ]


def validate_processing_readiness(upload_session: dict[str, Any], processing_plan: dict[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    upload_flags = upload_session.get("execution_flags") or {}
    if not upload_session.get("artifact_id"):
        blocking_issues.append(
            _issue("artifact_id_missing", "Processing session requires an artifact_id.", component="processing_session")
        )
    if not upload_session.get("upload_session_id"):
        blocking_issues.append(
            _issue(
                "upload_session_missing",
                "Processing session requires an upload_session_id.",
                component="upload_session",
            )
        )
    if not upload_flags.get("file_uploaded"):
        blocking_issues.append(
            _issue("binary_not_available", "Binary content is not uploaded yet.", component="binary_upload")
        )
    if not upload_flags.get("object_stored"):
        blocking_issues.append(
            _issue("storage_not_verified", "Stored object is not available for processing.", component="storage")
        )
    if upload_flags.get("ingestion_executed"):
        warnings.append(
            _issue(
                "ingestion_already_marked",
                "Upload session reports ingestion_executed=true before processing control plane execution.",
                component="processing_session",
                severity="warning",
            )
        )
    if not processing_plan.get("stages"):
        blocking_issues.append(
            _issue("processing_plan_empty", "Processing plan does not contain stages.", component="processing_plan")
        )
    return {
        "validation_status": "blocked" if blocking_issues else "planned",
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def build_processing_next_available_actions(processing_capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"action": action, **processing_capabilities[f"can_{action}"]} for action in FUTURE_PROCESSING_ACTIONS]


def build_processing_session(upload_session: dict[str, Any]) -> DocumentProcessingSession:
    processing_plan = build_processing_plan(upload_session)
    execution_flags = _execution_flags(upload_session)
    processing_capabilities = build_processing_capabilities(processing_plan, upload_session)
    pending_operations = build_pending_processing_operations(processing_capabilities)
    validation = validate_processing_readiness(upload_session, processing_plan)
    processing_state = (
        PROCESSING_SESSION_STATE_BLOCKED if validation["blocking_issues"] else PROCESSING_SESSION_STATE_PLANNED
    )
    return DocumentProcessingSession(
        processing_session_id=_processing_session_id(artifact_id=upload_session.get("artifact_id")),
        artifact_id=upload_session.get("artifact_id"),
        upload_session_id=upload_session.get("upload_session_id"),
        document_record_id=upload_session.get("document_record_id"),
        document_version_id=upload_session.get("document_version_id"),
        processing_state=processing_state,
        processing_plan=processing_plan,
        execution_flags=execution_flags,
        processing_capabilities=processing_capabilities,
        pending_operations=pending_operations,
        blocking_issues=validation["blocking_issues"],
        warnings=validation["warnings"],
        next_available_actions=build_processing_next_available_actions(processing_capabilities),
    )


def serialize_processing_session(processing_session: DocumentProcessingSession) -> dict[str, Any]:
    return {
        "processing_session_schema_version": PROCESSING_SESSION_SCHEMA_VERSION,
        "processing_session_id": processing_session.processing_session_id,
        "artifact_id": processing_session.artifact_id,
        "upload_session_id": processing_session.upload_session_id,
        "document_record_id": processing_session.document_record_id,
        "document_version_id": processing_session.document_version_id,
        "processing_state": processing_session.processing_state,
        "processing_plan": processing_session.processing_plan,
        "execution_flags": processing_session.execution_flags,
        "processing_capabilities": processing_session.processing_capabilities,
        "pending_operations": processing_session.pending_operations,
        "blocking_issues": processing_session.blocking_issues,
        "warnings": processing_session.warnings,
        "next_available_actions": processing_session.next_available_actions,
    }
