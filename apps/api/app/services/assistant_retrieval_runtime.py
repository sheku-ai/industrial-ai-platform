"""Metadata-only Assistant Retrieval Planning runtime."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRetrievalPlan, AssistantSession
from app.repositories.assistant import AssistantRepository
from app.services.assistant_retrieval_contracts import AssistantRetrievalRuntimePlan, AssistantRetrievalRuntimeResult
from app.services.assistant_retrieval_gateway import build_assistant_retrieval_gateway, build_assistant_retrieval_health
from app.services.assistant_retrieval_session import (
    build_assistant_retrieval_plan_request,
    build_assistant_retrieval_session,
)
from app.services.assistant_runtime import assistant_session_to_dict, assistant_to_dict


def assistant_retrieval_plan_to_dict(record: AssistantRetrievalPlan) -> dict[str, Any]:
    return {
        "retrieval_plan_id": str(record.retrieval_plan_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "plan_status": record.plan_status,
        "requested_query": record.requested_query,
        "selected_search_mode": record.selected_search_mode,
        "selected_runtime_domain": record.selected_runtime_domain,
        "execution_state": record.execution_state,
        "assistant_retrieval_runtime_prepared": True,
        "retrieval_plan_created": True,
        "enterprise_search_planned": bool(record.enterprise_search_planned),
        "semantic_search_planned": bool(record.semantic_search_planned),
        "hybrid_search_planned": bool(record.hybrid_search_planned),
        "retrieval_executed": bool(record.retrieval_executed),
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _runtime_plan(
    *,
    assistant_id: str,
    assistant_session_id: str | None,
    retrieval_plan_id: str | None,
    requested_query: str | None,
    selected_search_mode: str,
    runtime_metadata: dict[str, Any] | None = None,
) -> AssistantRetrievalRuntimePlan:
    request = build_assistant_retrieval_plan_request(
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        requested_query=requested_query,
        selected_search_mode=selected_search_mode,
        runtime_metadata=runtime_metadata,
    )
    return AssistantRetrievalRuntimePlan(
        session=build_assistant_retrieval_session(request),
        retrieval_plan_id=retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
    )


def build_assistant_retrieval_runtime(
    db: Session,
    *,
    assistant_id: str,
    assistant_session_id: str | None = None,
    organization_id: uuid.UUID | None = None,
    requested_query: str | None = None,
    selected_search_mode: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = build_assistant_retrieval_gateway(
        db,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        organization_id=organization_id,
        requested_query=requested_query,
        selected_search_mode=selected_search_mode,
        runtime_metadata=runtime_metadata,
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_retrieval_runtime_schema_version": "1",
            "assistant_retrieval_runtime_prepared": False,
            "assistant_retrieval_gateway": gateway,
            "retrieval_plan_created": False,
            "selected_search_mode": gateway.get("selected_search_mode") or "enterprise_search",
            "enterprise_search_planned": False,
            "hybrid_search_planned": False,
            "semantic_search_planned": False,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "passed": False,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    assistant = repository.get_scoped_assistant_definition(assistant_uuid, organization_id=organization_id)
    if assistant is None:
        return None
    if assistant_session_id:
        try:
            session_uuid = uuid.UUID(str(assistant_session_id))
        except (TypeError, ValueError):
            return None
        session = (
            repository.get_scoped_assistant_session(session_uuid, organization_id=organization_id)
            if organization_id is not None
            else repository.get_scoped_artifact(
                AssistantSession, AssistantSession.assistant_session_id, session_uuid, organization_id=None
            )
        )
        if session is None or session.assistant_id != assistant.assistant_id:
            return None
    else:
        session = repository.create_assistant_session(
            assistant_id=assistant.assistant_id, execution_organization_id=organization_id
        )
    search_mode = "enterprise_search"
    plan = repository.create_assistant_retrieval_plan(
        assistant_id=assistant.assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
        plan_status="planned",
        requested_query=requested_query,
        selected_search_mode=search_mode,
        selected_runtime_domain="enterprise_search",
        execution_state="metadata_only",
        enterprise_search_planned=True,
        semantic_search_planned=False,
        hybrid_search_planned=False,
        retrieval_executed=False,
        runtime_metadata={
            **dict(runtime_metadata or {}),
            "assistant_retrieval_runtime_prepared": True,
            "retrieval_plan_created": True,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    runtime_plan = _runtime_plan(
        assistant_id=str(assistant.assistant_id),
        assistant_session_id=str(session.assistant_session_id),
        retrieval_plan_id=str(plan.retrieval_plan_id),
        requested_query=requested_query,
        selected_search_mode=search_mode,
        runtime_metadata=runtime_metadata,
    )
    result = AssistantRetrievalRuntimeResult(
        runtime_plan=runtime_plan,
        plan_status=plan.plan_status,
        execution_state=plan.execution_state,
        retrieval_plan_created=True,
    )
    payload = {
        "assistant_retrieval_runtime_schema_version": "1",
        "assistant_retrieval_runtime_prepared": True,
        "assistant_retrieval_gateway": gateway,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(session),
        "assistant_retrieval_plan": assistant_retrieval_plan_to_dict(plan),
        "assistant_retrieval_runtime_plan": runtime_plan.as_dict(),
        "assistant_retrieval_runtime_result": result.as_dict(),
        "assistant_id": str(assistant.assistant_id),
        "assistant_session_id": str(session.assistant_session_id),
        "retrieval_plan_id": str(plan.retrieval_plan_id),
        "plan_status": plan.plan_status,
        "execution_state": plan.execution_state,
        "retrieval_plan_created": True,
        "assistant_session_created": assistant_session_id is None,
        "selected_search_mode": search_mode,
        "selected_runtime_domain": "enterprise_search",
        "enterprise_search_planned": True,
        "hybrid_search_planned": False,
        "semantic_search_planned": False,
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-retrieval-runtime:{plan.retrieval_plan_id}",
            artifact_id=None,
            runtime_outputs={"assistant_retrieval_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_retrieval_plan(db: Session, retrieval_plan_id: str) -> dict[str, Any] | None:
    try:
        plan_uuid = uuid.UUID(str(retrieval_plan_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_assistant_retrieval_plan(plan_uuid)
    return assistant_retrieval_plan_to_dict(record) if record is not None else None


__all__ = [
    "assistant_retrieval_plan_to_dict",
    "build_assistant_retrieval_health",
    "build_assistant_retrieval_runtime",
    "read_assistant_retrieval_plan",
]
