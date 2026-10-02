"""Assistant Context Builder runtime."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantContextPackage, AssistantSearchExecution
from app.repositories.assistant import AssistantRepository
from app.services.assistant_context_builder_gateway import (
    build_assistant_context_builder_gateway,
    build_assistant_context_builder_health,
)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4) if text else 0


def _result_rank(result: dict[str, Any]) -> int:
    value = result.get("ranking_position") or result.get("rank") or 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ordered_context(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for position, result in enumerate(
        sorted(results, key=lambda item: (_result_rank(item), str(item.get("search_result_id") or ""))), start=1
    ):
        text = str(result.get("text") or result.get("snippet") or result.get("highlighted_snippet") or "")
        citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
        ordered.append(
            {
                "context_index": position,
                "search_result_id": result.get("search_result_id"),
                "ranking_position": _result_rank(result) or position,
                "score": result.get("score"),
                "text": text,
                "snippet": result.get("snippet") or result.get("highlighted_snippet"),
                "artifact_id": result.get("artifact_id"),
                "publication_id": result.get("publication_id"),
                "knowledge_document_id": result.get("knowledge_document_id"),
                "knowledge_chunk_id": result.get("knowledge_chunk_id"),
                "published_chunk_id": result.get("published_chunk_id"),
                "chunk_index": result.get("chunk_index"),
                "content_hash": result.get("content_hash"),
                "semantic_hash": result.get("semantic_hash"),
                "citation_id": citation.get("citation_id"),
                "token_estimate": _estimate_tokens(text),
            }
        )
    return ordered


def _ordered_citations(results: list[dict[str, Any]], citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("citation_id")): dict(item)
        for item in citations
        if isinstance(item, dict) and item.get("citation_id")
    }
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, result in enumerate(
        sorted(results, key=lambda item: (_result_rank(item), str(item.get("search_result_id") or ""))), start=1
    ):
        citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
        citation_id = str(citation.get("citation_id") or "")
        if not citation_id or citation_id in seen:
            continue
        seen.add(citation_id)
        payload = {**citation, **by_id.get(citation_id, {})}
        payload["citation_index"] = position
        ordered.append(payload)
    return ordered


def assistant_context_package_to_dict(record: AssistantContextPackage) -> dict[str, Any]:
    return {
        "context_package_id": str(record.context_package_id),
        "search_execution_id": str(record.search_execution_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "package_status": record.package_status,
        "chunk_count": int(record.chunk_count or 0),
        "citation_count": int(record.citation_count or 0),
        "total_tokens_estimated": int(record.total_tokens_estimated or 0),
        "context_size_bytes": int(record.context_size_bytes or 0),
        "truncation_required": bool(record.truncation_required),
        "truncation_applied": bool(record.truncation_applied),
        "ordered_context": list(record.ordered_context or []),
        "ordered_citations": list(record.ordered_citations or []),
        "package_metadata": record.package_metadata or {},
        "assistant_context_builder_prepared": True,
        "context_package_created": True,
        "ordered_context_created": bool(record.ordered_context),
        "ordered_citations_created": bool(record.ordered_citations),
        "chunk_count_gt_zero": int(record.chunk_count or 0) > 0,
        "citation_count_gt_zero": int(record.citation_count or 0) > 0,
        "token_estimation_completed": int(record.total_tokens_estimated or 0) > 0,
        "llm_used": False,
        "answer_generated": False,
        "workflow_executed": False,
        "tool_called": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def build_assistant_context_builder_runtime(
    db: Session,
    *,
    search_execution_id: str,
    organization_id: uuid.UUID | None = None,
    package_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    scoped_repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(search_execution_id))
    except (TypeError, ValueError):
        return None
    scoped_artifact = scoped_repository.get_scoped_artifact(
        AssistantSearchExecution,
        AssistantSearchExecution.search_execution_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if scoped_artifact is None or (scoped_artifact.ownership_scope == "organization" and organization_id is None):
        return None
    gateway = build_assistant_context_builder_gateway(
        db, search_execution_id=search_execution_id, package_metadata=package_metadata
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_context_builder_schema_version": "1",
            "assistant_context_builder_prepared": False,
            "assistant_context_builder_gateway": gateway,
            "search_execution_completed": False,
            "context_package_created": False,
            "ordered_context_created": False,
            "ordered_citations_created": False,
            "chunk_count_gt_zero": False,
            "citation_count_gt_zero": False,
            "token_estimation_completed": False,
            "truncation_required": False,
            "truncation_applied": False,
            "llm_used": False,
            "answer_generated": False,
            "workflow_executed": False,
            "tool_called": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = AssistantRepository(db)
    search_execution = scoped_artifact
    if search_execution is None:
        return None
    metadata = search_execution.execution_metadata or {}
    results = metadata.get("results") if isinstance(metadata.get("results"), list) else []
    citations = metadata.get("citations") if isinstance(metadata.get("citations"), list) else []
    ordered_context = _ordered_context(results)
    ordered_citations = _ordered_citations(results, citations)
    context_size_bytes = len(json.dumps(ordered_context, sort_keys=True, default=str).encode("utf-8"))
    total_tokens_estimated = sum(int(item.get("token_estimate") or 0) for item in ordered_context)
    context_package = repository.create_context_package(
        search_execution_id=search_execution.search_execution_id,
        assistant_id=search_execution.assistant_id,
        assistant_session_id=search_execution.assistant_session_id,
        package_status="created",
        chunk_count=len(ordered_context),
        citation_count=len(ordered_citations),
        total_tokens_estimated=total_tokens_estimated,
        context_size_bytes=context_size_bytes,
        truncation_required=False,
        truncation_applied=False,
        ordered_context=ordered_context,
        ordered_citations=ordered_citations,
        package_metadata={
            **dict(package_metadata or {}),
            "assistant_context_builder_prepared": True,
            "search_execution_completed": True,
            "context_package_created": True,
            "ordered_context_created": bool(ordered_context),
            "ordered_citations_created": bool(ordered_citations),
            "token_estimation_completed": total_tokens_estimated > 0,
            "prompt_generated": False,
            "llm_used": False,
            "answer_generated": False,
            "workflow_executed": False,
            "tool_called": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    payload = {
        "assistant_context_builder_schema_version": "1",
        "assistant_context_builder_prepared": True,
        "assistant_context_builder_gateway": gateway,
        "assistant_context_package": assistant_context_package_to_dict(context_package),
        "context_package_id": str(context_package.context_package_id),
        "search_execution_id": str(search_execution.search_execution_id),
        "assistant_id": str(search_execution.assistant_id),
        "assistant_session_id": str(search_execution.assistant_session_id)
        if search_execution.assistant_session_id
        else None,
        "search_execution_completed": True,
        "context_package_created": True,
        "ordered_context_created": bool(ordered_context),
        "ordered_citations_created": bool(ordered_citations),
        "chunk_count": len(ordered_context),
        "citation_count": len(ordered_citations),
        "chunk_count_gt_zero": len(ordered_context) > 0,
        "citation_count_gt_zero": len(ordered_citations) > 0,
        "total_tokens_estimated": total_tokens_estimated,
        "context_size_bytes": context_size_bytes,
        "token_estimation_completed": total_tokens_estimated > 0,
        "truncation_required": False,
        "truncation_applied": False,
        "llm_used": False,
        "answer_generated": False,
        "workflow_executed": False,
        "tool_called": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": bool(ordered_context) and bool(ordered_citations) and total_tokens_estimated > 0,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-context-builder:{context_package.context_package_id}",
            artifact_id=None,
            runtime_outputs={"assistant_context_builder": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_context_package(db: Session, context_package_id: str) -> dict[str, Any] | None:
    try:
        context_package_uuid = uuid.UUID(str(context_package_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_context_package(context_package_uuid)
    return assistant_context_package_to_dict(record) if record is not None else None


__all__ = [
    "assistant_context_package_to_dict",
    "build_assistant_context_builder_health",
    "build_assistant_context_builder_runtime",
    "read_assistant_context_package",
]
