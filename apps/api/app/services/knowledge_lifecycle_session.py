"""Knowledge Lifecycle session foundation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

KNOWLEDGE_LIFECYCLE_SESSION_SCHEMA_VERSION = "1"
KNOWLEDGE_LIFECYCLE_RUNTIME_VERSION = "knowledge_lifecycle_runtime/1.0"
KNOWLEDGE_LIFECYCLE_STATE_BLOCKED = "blocked"
KNOWLEDGE_LIFECYCLE_STATE_READY = "ready"

REINDEX_MODES = {"FULL", "INCREMENTAL", "DOCUMENT", "PUBLICATION", "ARTIFACT"}
OPERATIONS = {"initial_indexing", "incremental", "reindex", "cleanup", "rebuild", "health", "statistics"}


@dataclass(frozen=True)
class KnowledgeLifecycleSession:
    lifecycle_session_id: str | None
    operation: str
    mode: str
    artifact_id: str | None
    publication_id: str | None
    document_id: str | None
    lifecycle_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def issue(
    code: str, message: str, *, component: str, severity: str = "blocking", item_id: str | None = None
) -> dict[str, Any]:
    return {"code": code, "severity": severity, "component": component, "item_id": item_id, "message": message}


def sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _stable_session_id(
    *, operation: str, mode: str, artifact_id: str | None, publication_id: str | None, document_id: str | None
) -> str:
    seed = "|".join([operation, mode, artifact_id or "", publication_id or "", document_id or ""])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"knowledge-lifecycle-session:{digest}"


def build_knowledge_lifecycle_session(
    *,
    operation: str,
    mode: str = "INCREMENTAL",
    artifact_id: str | None = None,
    publication_id: str | None = None,
    document_id: str | None = None,
    publication_result: dict[str, Any] | None = None,
) -> KnowledgeLifecycleSession:
    requested_operation = str(operation or "").strip()
    requested_mode = str(mode or "INCREMENTAL").strip().upper()
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    publication_payload = publication_result if isinstance(publication_result, dict) else {}
    if not requested_operation:
        blocking_issues.append(
            issue("operation_missing", "Knowledge lifecycle requires an operation.", component="knowledge_lifecycle")
        )
    elif requested_operation not in OPERATIONS:
        blocking_issues.append(
            issue(
                "operation_unsupported",
                "Knowledge lifecycle operation is not supported.",
                component="knowledge_lifecycle",
                item_id=requested_operation,
            )
        )
    if requested_mode not in REINDEX_MODES:
        blocking_issues.append(
            issue(
                "mode_unsupported",
                "Knowledge lifecycle mode is not supported.",
                component="knowledge_lifecycle",
                item_id=requested_mode,
            )
        )
    resolved_artifact_id = artifact_id or publication_payload.get("artifact_id")
    resolved_publication_id = publication_id or publication_payload.get("publication_id")
    if requested_mode == "DOCUMENT" and not document_id:
        blocking_issues.append(
            issue(
                "document_id_missing", "DOCUMENT lifecycle mode requires document_id.", component="knowledge_lifecycle"
            )
        )
    if requested_mode == "PUBLICATION" and not resolved_publication_id:
        blocking_issues.append(
            issue(
                "publication_id_missing",
                "PUBLICATION lifecycle mode requires publication_id.",
                component="knowledge_lifecycle",
            )
        )
    if requested_mode == "ARTIFACT" and not resolved_artifact_id:
        blocking_issues.append(
            issue(
                "artifact_id_missing", "ARTIFACT lifecycle mode requires artifact_id.", component="knowledge_lifecycle"
            )
        )
    if (
        requested_operation in {"initial_indexing", "incremental"}
        and publication_payload
        and (
            publication_payload.get("publication_completed") is not True
            or publication_payload.get("knowledge_published") is not True
        )
    ):
        blocking_issues.append(
            issue(
                "publication_not_ready",
                "Lifecycle indexing requires a completed publication result.",
                component="knowledge_lifecycle",
            )
        )
    ready = not blocking_issues
    return KnowledgeLifecycleSession(
        lifecycle_session_id=_stable_session_id(
            operation=requested_operation,
            mode=requested_mode,
            artifact_id=str(resolved_artifact_id) if resolved_artifact_id else None,
            publication_id=str(resolved_publication_id) if resolved_publication_id else None,
            document_id=str(document_id) if document_id else None,
        ),
        operation=requested_operation,
        mode=requested_mode,
        artifact_id=str(resolved_artifact_id) if resolved_artifact_id else None,
        publication_id=str(resolved_publication_id) if resolved_publication_id else None,
        document_id=str(document_id) if document_id else None,
        lifecycle_state=KNOWLEDGE_LIFECYCLE_STATE_READY if ready else KNOWLEDGE_LIFECYCLE_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "execute_knowledge_lifecycle",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "knowledge_lifecycle_session_blocked",
            }
        ],
    )


def serialize_knowledge_lifecycle_session(session: KnowledgeLifecycleSession) -> dict[str, Any]:
    return {
        "knowledge_lifecycle_session_schema_version": KNOWLEDGE_LIFECYCLE_SESSION_SCHEMA_VERSION,
        "lifecycle_session_id": session.lifecycle_session_id,
        "operation": session.operation,
        "mode": session.mode,
        "artifact_id": session.artifact_id,
        "publication_id": session.publication_id,
        "document_id": session.document_id,
        "lifecycle_state": session.lifecycle_state,
        "lifecycle_session_ready": session.lifecycle_state == KNOWLEDGE_LIFECYCLE_STATE_READY,
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "persistence_status": "not_persisted",
    }
