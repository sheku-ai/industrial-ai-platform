"""Runtime Persistence session foundation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

RUNTIME_PERSISTENCE_SESSION_SCHEMA_VERSION = "1"
RUNTIME_PERSISTENCE_STATE_BLOCKED = "blocked"
RUNTIME_PERSISTENCE_STATE_READY = "ready"


@dataclass(frozen=True)
class RuntimePersistenceSession:
    persistence_session_id: str | None
    execution_id: str | None
    artifact_id: str | None
    requested_domains: list[str]
    persistence_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def issue(
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


def sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def stable_persistence_session_id(execution_id: str | None) -> str | None:
    if not execution_id:
        return None
    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:24]
    return f"runtime-persistence-session:{digest}"


def build_runtime_persistence_session(
    *,
    execution_id: str | None,
    artifact_id: str | None,
    runtime_outputs: dict[str, Any],
) -> RuntimePersistenceSession:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not execution_id:
        blocking_issues.append(
            issue(
                "execution_id_missing", "Runtime persistence requires an execution_id.", component="runtime_persistence"
            )
        )
    if not isinstance(runtime_outputs, dict) or not runtime_outputs:
        blocking_issues.append(
            issue(
                "runtime_outputs_missing",
                "Runtime persistence requires runtime output payloads.",
                component="runtime_persistence",
            )
        )
    supported_domains = (
        "storage",
        "processing",
        "chunk",
        "knowledge_publication",
        "knowledge_index",
        "knowledge_lifecycle",
        "knowledge_fts",
        "embedding_runtime",
        "vector_index_runtime",
        "semantic_search_runtime",
        "hybrid_search_runtime",
        "workflow_runtime",
        "assistant_runtime",
        "assistant_retrieval_runtime",
        "assistant_retrieval_execution_readiness",
        "assistant_search_execution",
        "assistant_context_builder",
        "assistant_prompt_assembly",
        "assistant_llm_gateway",
        "assistant_llm_execution",
        "assistant_citation_verification",
        "assistant_response",
        "conversation_runtime",
        "chat_runtime",
        "enterprise_search",
    )
    domains = [domain for domain in supported_domains if runtime_outputs.get(domain) is not None]
    if not domains:
        blocking_issues.append(
            issue(
                "runtime_domains_missing",
                "Runtime persistence requires at least one supported runtime domain.",
                component="runtime_persistence",
            )
        )
    expected = set(supported_domains)
    missing = sorted(expected.difference(domains))
    if missing:
        warnings.append(
            issue(
                "runtime_domains_partial",
                "Runtime persistence received a partial runtime chain.",
                component="runtime_persistence",
                severity="warning",
                item_id=",".join(missing),
            )
        )
    ready = not blocking_issues
    return RuntimePersistenceSession(
        persistence_session_id=stable_persistence_session_id(execution_id),
        execution_id=execution_id,
        artifact_id=artifact_id,
        requested_domains=domains,
        persistence_state=RUNTIME_PERSISTENCE_STATE_READY if ready else RUNTIME_PERSISTENCE_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "persist_runtime_outputs",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "runtime_persistence_session_blocked",
            }
        ],
    )


def serialize_runtime_persistence_session(session: RuntimePersistenceSession) -> dict[str, Any]:
    return {
        "runtime_persistence_session_schema_version": RUNTIME_PERSISTENCE_SESSION_SCHEMA_VERSION,
        "persistence_session_id": session.persistence_session_id,
        "execution_id": session.execution_id,
        "artifact_id": session.artifact_id,
        "requested_domains": list(session.requested_domains),
        "persistence_state": session.persistence_state,
        "persistence_session_ready": session.persistence_state == RUNTIME_PERSISTENCE_STATE_READY,
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "persistence_status": "not_persisted",
    }
