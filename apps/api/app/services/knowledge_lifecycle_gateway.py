"""Knowledge Lifecycle gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.knowledge_lifecycle_session import (
    build_knowledge_lifecycle_session,
    serialize_knowledge_lifecycle_session,
)

KNOWLEDGE_LIFECYCLE_GATEWAY_SCHEMA_VERSION = "1"
KNOWLEDGE_LIFECYCLE_GATEWAY_STATUS_BLOCKED = "blocked"
KNOWLEDGE_LIFECYCLE_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class KnowledgeLifecycleGateway:
    lifecycle_session: dict[str, Any]
    gateway_status: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def build_knowledge_lifecycle_gateway(
    *,
    operation: str,
    mode: str = "INCREMENTAL",
    artifact_id: str | None = None,
    publication_id: str | None = None,
    document_id: str | None = None,
    publication_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lifecycle_session = serialize_knowledge_lifecycle_session(
        build_knowledge_lifecycle_session(
            operation=operation,
            mode=mode,
            artifact_id=artifact_id,
            publication_id=publication_id,
            document_id=document_id,
            publication_result=publication_result,
        )
    )
    ready = bool(lifecycle_session.get("lifecycle_session_ready"))
    gateway = KnowledgeLifecycleGateway(
        lifecycle_session=lifecycle_session,
        gateway_status=KNOWLEDGE_LIFECYCLE_GATEWAY_STATUS_READY
        if ready
        else KNOWLEDGE_LIFECYCLE_GATEWAY_STATUS_BLOCKED,
        blocking_issues=lifecycle_session.get("blocking_issues") or [],
        warnings=lifecycle_session.get("warnings") or [],
        next_available_actions=[
            {
                "action": "execute_knowledge_lifecycle",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "knowledge_lifecycle_gateway_blocked",
            }
        ],
    )
    serialized = {
        "knowledge_lifecycle_gateway_schema_version": KNOWLEDGE_LIFECYCLE_GATEWAY_SCHEMA_VERSION,
        "lifecycle_gateway_ready": ready,
        "gateway_status": gateway.gateway_status,
        "lifecycle_session": dict(gateway.lifecycle_session),
        "blocking_issues": list(gateway.blocking_issues),
        "warnings": list(gateway.warnings),
        "next_available_actions": list(gateway.next_available_actions),
        "persistence_status": "not_persisted",
    }
    return {**serialized, "knowledge_lifecycle_gateway": serialized}
