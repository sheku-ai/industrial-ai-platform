"""Assistant Enterprise Search Execution runtime."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantRetrievalExecutionPlan,
    AssistantRetrievalPlan,
    AssistantSearchExecution,
    AssistantSession,
)
from app.repositories.assistant import AssistantRepository
from app.services.assistant_retrieval_execution_runtime import assistant_retrieval_execution_plan_to_dict
from app.services.assistant_retrieval_runtime import assistant_retrieval_plan_to_dict
from app.services.assistant_runtime import assistant_session_to_dict, assistant_to_dict
from app.services.assistant_search_execution_gateway import (
    build_assistant_search_execution_gateway,
    build_assistant_search_execution_health,
)
from app.services.enterprise_search_assistant_gate import (
    evaluate_enterprise_search_assistant_gate_v1,
    serialize_enterprise_search_assistant_gate_v1,
)
from app.services.enterprise_search_runtime import build_enterprise_search
from app.services.enterprise_search_session import issue, sort_issues


def _assistant_context_acceptance_issues(
    *,
    search_completed: bool,
    result_count: int,
    postgresql_fts_used: bool,
) -> list[dict[str, Any]]:
    if search_completed and postgresql_fts_used and result_count <= 0:
        return [
            issue(
                "search_results_empty",
                "Assistant context cannot be built because Enterprise Search produced no matching results.",
                component="assistant_search_execution",
            )
        ]
    return []


def assistant_search_execution_to_dict(record: AssistantSearchExecution) -> dict[str, Any]:
    context_eligible = bool(
        record.search_completed and record.postgresql_fts_used and int(record.result_count or 0) > 0
    )
    return {
        "search_execution_id": str(record.search_execution_id),
        "execution_plan_id": str(record.execution_plan_id),
        "retrieval_plan_id": str(record.retrieval_plan_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "search_mode": record.search_mode,
        "runtime_domain": record.runtime_domain,
        "search_query": record.search_query,
        "search_completed": bool(record.search_completed),
        "enterprise_search_executed": bool(record.search_completed),
        "search_duration_ms": record.search_duration_ms,
        "result_count": int(record.result_count or 0),
        "result_count_gt_zero": int(record.result_count or 0) > 0,
        "context_eligible": context_eligible,
        "lexical_search_used": bool(record.lexical_search_used),
        "postgresql_fts_used": bool(record.postgresql_fts_used),
        "semantic_search_used": bool(record.semantic_search_used),
        "hybrid_search_used": bool(record.hybrid_search_used),
        "qdrant_used": bool(record.qdrant_used),
        "reranking_used": bool(record.reranking_used),
        "llm_used": bool(record.llm_used),
        "answer_generated": bool(record.answer_generated),
        "tool_called": bool(record.tool_called),
        "workflow_executed": bool(record.workflow_executed),
        "external_action_called": bool(record.external_action_called),
        "autonomous_execution": bool(record.autonomous_execution),
        "postgresql_source_of_truth": True,
        "execution_metadata": record.execution_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _organization_id_from_search_context(
    search_config: dict[str, Any] | None,
    runtime_metadata: dict[str, Any] | None,
) -> str | None:
    config = search_config if isinstance(search_config, dict) else {}
    filters = config.get("filters") if isinstance(config.get("filters"), dict) else {}
    organization_id = filters.get("organization_id") or config.get("organization_id")
    if organization_id:
        return str(organization_id)
    metadata = runtime_metadata if isinstance(runtime_metadata, dict) else {}
    metadata_filters = metadata.get("filters") if isinstance(metadata.get("filters"), dict) else {}
    organization_id = metadata.get("organization_id") or metadata_filters.get("organization_id")
    return str(organization_id) if organization_id else None


def _scoped_search_config(
    search_config: dict[str, Any] | None,
    runtime_metadata: dict[str, Any] | None,
    *,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    scoped = dict(search_config or {})
    effective_id = str(organization_id) if organization_id is not None else _organization_id_from_search_context(
        scoped, runtime_metadata
    )
    if not effective_id:
        return scoped
    filters = dict(scoped.get("filters") or {})
    if organization_id is None:
        filters.setdefault("organization_id", effective_id)
        scoped.setdefault("organization_id", effective_id)
    else:
        filters["organization_id"] = effective_id
        scoped["organization_id"] = effective_id
    scoped["filters"] = filters
    return scoped


def _enterprise_search_evidence_id(enterprise_search: dict[str, Any]) -> uuid.UUID | None:
    persistence = enterprise_search.get("runtime_persistence")
    if not isinstance(persistence, dict):
        return None
    for record in persistence.get("persisted_records") or []:
        if not isinstance(record, dict):
            continue
        if record.get("runtime_domain") != "enterprise_search" or record.get("record_type") != "search_result_set":
            continue
        try:
            return uuid.UUID(str(record.get("id")))
        except (TypeError, ValueError):
            return None
    return None


def _blocked_search_evidence_result(
    *,
    gateway: dict[str, Any],
    assistant: Any,
    session: Any,
    retrieval_plan: Any,
    execution_plan: Any,
    enterprise_search: dict[str, Any],
    search_query: str,
    organization_id: str | None,
    duration_ms: int,
    blocking_issues: list[dict[str, Any]],
    gate_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "assistant_search_execution_schema_version": "1",
        "assistant_search_execution_prepared": False,
        "assistant_search_execution_gateway": gateway,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(session) if session is not None else None,
        "assistant_retrieval_plan": assistant_retrieval_plan_to_dict(retrieval_plan),
        "assistant_retrieval_execution_plan": assistant_retrieval_execution_plan_to_dict(execution_plan),
        "assistant_search_execution": None,
        "enterprise_search": enterprise_search,
        "enterprise_search_evidence_gate": gate_payload,
        "search_execution_id": None,
        "execution_plan_id": str(execution_plan.execution_plan_id),
        "retrieval_plan_id": str(retrieval_plan.retrieval_plan_id),
        "assistant_id": str(assistant.assistant_id),
        "assistant_session_id": str(execution_plan.assistant_session_id)
        if execution_plan.assistant_session_id
        else None,
        "retrieval_plan_created": True,
        "execution_readiness_created": True,
        "enterprise_search_executed": bool(enterprise_search.get("search_completed")),
        "search_completed": bool(enterprise_search.get("search_completed")),
        "search_query": search_query,
        "organization_id": organization_id,
        "search_duration_ms": duration_ms,
        "result_count": int(enterprise_search.get("result_count") or 0),
        "result_count_gt_zero": int(enterprise_search.get("result_count") or 0) > 0,
        "context_eligible": False,
        "selected_search_mode": "enterprise_search",
        "selected_runtime_domain": "enterprise_search",
        "lexical_search_used": True,
        "postgresql_fts_used": bool(enterprise_search.get("search_uses_postgresql_fts")),
        "semantic_search_used": False,
        "hybrid_search_used": False,
        "qdrant_used": False,
        "reranking_used": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
        "passed": False,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": list(gateway.get("warnings") or []) + list(enterprise_search.get("warnings") or []),
    }


def build_assistant_search_execution_runtime(
    db: Session,
    *,
    execution_plan_id: str,
    organization_id: uuid.UUID | None = None,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = build_assistant_search_execution_gateway(
        db,
        execution_plan_id=execution_plan_id,
        organization_id=organization_id,
        top_k=top_k,
        search_config=search_config,
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_search_execution_schema_version": "1",
            "assistant_search_execution_prepared": False,
            "assistant_search_execution_gateway": gateway,
            "retrieval_plan_created": False,
            "execution_readiness_created": False,
            "enterprise_search_executed": False,
            "postgresql_fts_used": False,
            "lexical_search_used": False,
            "result_count_gt_zero": False,
            "search_completed": False,
            "semantic_search_used": False,
            "hybrid_search_used": False,
            "qdrant_used": False,
            "reranking_used": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    try:
        execution_plan_uuid = uuid.UUID(str(execution_plan_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    execution_plan = repository.get_scoped_artifact(
        AssistantRetrievalExecutionPlan,
        AssistantRetrievalExecutionPlan.execution_plan_id,
        execution_plan_uuid,
        organization_id=organization_id,
    )
    if execution_plan is None:
        return None
    effective_organization_id = execution_plan.organization_id
    retrieval_plan = repository.get_scoped_artifact(
        AssistantRetrievalPlan,
        AssistantRetrievalPlan.retrieval_plan_id,
        execution_plan.retrieval_plan_id,
        organization_id=effective_organization_id,
    )
    assistant = repository.get_scoped_assistant_definition(
        execution_plan.assistant_id, organization_id=effective_organization_id
    )
    if retrieval_plan is None or assistant is None:
        return None
    if (
        retrieval_plan.assistant_id != execution_plan.assistant_id
        or retrieval_plan.assistant_session_id != execution_plan.assistant_session_id
        or retrieval_plan.organization_id != effective_organization_id
        or retrieval_plan.ownership_scope != execution_plan.ownership_scope
    ):
        return None
    scoped_search_config = _scoped_search_config(
        search_config, retrieval_plan.runtime_metadata or {}, organization_id=effective_organization_id
    )
    session = (
        (
            repository.get_scoped_assistant_session(
                execution_plan.assistant_session_id, organization_id=effective_organization_id
            )
            if effective_organization_id is not None
            else repository.get_scoped_artifact(
                AssistantSession,
                AssistantSession.assistant_session_id,
                execution_plan.assistant_session_id,
                organization_id=None,
            )
        )
        if execution_plan.assistant_session_id
        else None
    )
    if execution_plan.assistant_session_id is not None and (
        session is None or session.assistant_id != execution_plan.assistant_id
    ):
        return None
    search_query = str(retrieval_plan.requested_query or "").strip()
    started = time.perf_counter()
    enterprise_search = build_enterprise_search(
        db=db,
        query=search_query,
        top_k=max(1, min(int(top_k or 10), 50)),
        search_config=scoped_search_config,
        persist_snapshot=True,
    )
    duration_ms = int(round((time.perf_counter() - started) * 1000))
    result_count = int(enterprise_search.get("result_count") or 0)
    search_completed = bool(enterprise_search.get("search_completed"))
    postgresql_fts_used = bool(enterprise_search.get("search_uses_postgresql_fts"))
    search_results = enterprise_search.get("results") if isinstance(enterprise_search.get("results"), list) else []
    search_citations = (
        enterprise_search.get("citations") if isinstance(enterprise_search.get("citations"), list) else []
    )
    blocking_issues = list(enterprise_search.get("blocking_issues") or [])

    search_organization_id = (
        str(effective_organization_id)
        if effective_organization_id is not None
        else enterprise_search.get("organization_id") or scoped_search_config.get("organization_id")
    )
    if effective_organization_id is not None and enterprise_search.get("organization_id") not in (
        None,
        str(effective_organization_id),
    ):
        blocking_issues.append(
            issue(
                "search_organization_scope_mismatch",
                "Enterprise Search returned a different organization than persisted execution ownership.",
                component="assistant_search_execution",
            )
        )
    evidence_id = _enterprise_search_evidence_id(enterprise_search)
    gate_payload: dict[str, Any] | None = None
    if not blocking_issues:
        try:
            organization_uuid = uuid.UUID(str(search_organization_id))
        except (TypeError, ValueError):
            organization_uuid = None
        if organization_uuid is None or evidence_id is None:
            blocking_issues.append(
                issue(
                    "enterprise_search_evidence_missing",
                    "Assistant execution requires persisted Enterprise Search evidence.",
                    component="enterprise_search_evidence",
                )
            )
        else:
            search_gate = evaluate_enterprise_search_assistant_gate_v1(
                db,
                organization_id=organization_uuid,
                evidence_id=evidence_id,
                expected_query=search_query,
            )
            gate_payload = serialize_enterprise_search_assistant_gate_v1(search_gate)
            blocking_issues.extend(search_gate.blocking_issues)

    if blocking_issues:
        return _blocked_search_evidence_result(
            gateway=gateway,
            assistant=assistant,
            session=session,
            retrieval_plan=retrieval_plan,
            execution_plan=execution_plan,
            enterprise_search=enterprise_search,
            search_query=search_query,
            organization_id=str(search_organization_id) if search_organization_id else None,
            duration_ms=duration_ms,
            blocking_issues=blocking_issues,
            gate_payload=gate_payload,
        )

    blocking_issues.extend(
        _assistant_context_acceptance_issues(
            search_completed=search_completed,
            result_count=result_count,
            postgresql_fts_used=postgresql_fts_used,
        )
    )
    context_eligible = bool(
        search_completed and postgresql_fts_used and result_count > 0 and not blocking_issues
    )
    search_execution = repository.create_assistant_search_execution(
        execution_plan_id=execution_plan.execution_plan_id,
        retrieval_plan_id=execution_plan.retrieval_plan_id,
        assistant_id=execution_plan.assistant_id,
        assistant_session_id=execution_plan.assistant_session_id,
        search_mode="enterprise_search",
        runtime_domain="enterprise_search",
        search_query=search_query,
        search_completed=search_completed,
        search_duration_ms=duration_ms,
        result_count=result_count,
        lexical_search_used=True,
        postgresql_fts_used=postgresql_fts_used,
        semantic_search_used=False,
        hybrid_search_used=False,
        qdrant_used=False,
        reranking_used=False,
        llm_used=False,
        answer_generated=False,
        tool_called=False,
        workflow_executed=False,
        external_action_called=False,
        autonomous_execution=False,
        execution_metadata={
            "assistant_search_execution_prepared": True,
            "enterprise_search_executed": search_completed,
            "enterprise_search_evidence_gate": gate_payload,
            "search_completed": search_completed,
            "result_count": result_count,
            "context_eligible": context_eligible,
            "results": search_results,
            "citations": search_citations,
            "search_duration_ms": duration_ms,
            "lexical_search_used": True,
            "postgresql_fts_used": postgresql_fts_used,
            "semantic_search_used": False,
            "hybrid_search_used": False,
            "qdrant_used": False,
            "reranking_used": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "organization_id": str(search_organization_id) if search_organization_id else None,
        },
    )
    db.commit()
    payload = {
        "assistant_search_execution_schema_version": "1",
        "assistant_search_execution_prepared": True,
        "assistant_search_execution_gateway": gateway,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(session) if session is not None else None,
        "assistant_retrieval_plan": assistant_retrieval_plan_to_dict(retrieval_plan),
        "assistant_retrieval_execution_plan": assistant_retrieval_execution_plan_to_dict(execution_plan),
        "assistant_search_execution": assistant_search_execution_to_dict(search_execution),
        "enterprise_search": enterprise_search,
        "enterprise_search_evidence_gate": gate_payload,
        "search_execution_id": str(search_execution.search_execution_id),
        "execution_plan_id": str(execution_plan.execution_plan_id),
        "retrieval_plan_id": str(retrieval_plan.retrieval_plan_id),
        "assistant_id": str(assistant.assistant_id),
        "assistant_session_id": str(execution_plan.assistant_session_id)
        if execution_plan.assistant_session_id
        else None,
        "retrieval_plan_created": True,
        "execution_readiness_created": True,
        "enterprise_search_executed": search_completed,
        "search_completed": search_completed,
        "search_query": search_query,
        "organization_id": str(search_organization_id) if search_organization_id else None,
        "search_duration_ms": duration_ms,
        "result_count": result_count,
        "result_count_gt_zero": result_count > 0,
        "context_eligible": context_eligible,
        "selected_search_mode": "enterprise_search",
        "selected_runtime_domain": "enterprise_search",
        "lexical_search_used": True,
        "postgresql_fts_used": postgresql_fts_used,
        "semantic_search_used": False,
        "hybrid_search_used": False,
        "qdrant_used": False,
        "reranking_used": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": context_eligible,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": list(gateway.get("warnings") or []) + list(enterprise_search.get("warnings") or []),
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-search-execution:{search_execution.search_execution_id}",
            artifact_id=None,
            runtime_outputs={"assistant_search_execution": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_search_execution(db: Session, search_execution_id: str) -> dict[str, Any] | None:
    try:
        search_execution_uuid = uuid.UUID(str(search_execution_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_assistant_search_execution(search_execution_uuid)
    return assistant_search_execution_to_dict(record) if record is not None else None


__all__ = [
    "assistant_search_execution_to_dict",
    "build_assistant_search_execution_health",
    "build_assistant_search_execution_runtime",
    "read_assistant_search_execution",
]
