"""Metadata-only Assistant Retrieval Execution Readiness runtime."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRetrievalExecutionPlan, AssistantRetrievalPlan, AssistantSession
from app.repositories.assistant import AssistantRepository
from app.services.assistant_retrieval_execution_contracts import AssistantRetrievalExecutionRuntimePlan
from app.services.assistant_retrieval_execution_gateway import (
    build_assistant_retrieval_execution_gateway,
    build_assistant_retrieval_execution_health,
)
from app.services.assistant_retrieval_execution_session import (
    build_assistant_retrieval_execution_request,
    build_assistant_retrieval_execution_session,
)
from app.services.assistant_retrieval_runtime import assistant_retrieval_plan_to_dict
from app.services.assistant_runtime import assistant_session_to_dict, assistant_to_dict


def assistant_retrieval_execution_plan_to_dict(record: AssistantRetrievalExecutionPlan) -> dict[str, Any]:
    return {
        "execution_plan_id": str(record.execution_plan_id),
        "retrieval_plan_id": str(record.retrieval_plan_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "execution_status": record.execution_status,
        "selected_search_mode": record.selected_search_mode,
        "selected_runtime_domain": record.selected_runtime_domain,
        "execution_state": record.execution_state,
        "assistant_retrieval_execution_readiness_prepared": True,
        "retrieval_plan_created": True,
        "execution_readiness_created": True,
        "enterprise_search_execution_prepared": bool(record.enterprise_search_execution_prepared),
        "semantic_search_execution_prepared": bool(record.semantic_search_execution_prepared),
        "hybrid_search_execution_prepared": bool(record.hybrid_search_execution_prepared),
        "retrieval_executed": bool(record.retrieval_executed),
        "answer_generated": bool(record.answer_generated),
        "llm_used": bool(record.llm_used),
        "tool_called": bool(record.tool_called),
        "workflow_executed": bool(record.workflow_executed),
        "external_action_called": bool(record.external_action_called),
        "autonomous_execution": bool(record.autonomous_execution),
        "postgresql_source_of_truth": True,
        "readiness_metadata": record.readiness_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _runtime_plan(
    *,
    retrieval_plan_id: str,
    assistant_id: str,
    assistant_session_id: str | None,
    execution_plan_id: str | None,
    selected_search_mode: str,
    selected_runtime_domain: str,
    readiness_metadata: dict[str, Any] | None = None,
) -> AssistantRetrievalExecutionRuntimePlan:
    request = build_assistant_retrieval_execution_request(
        retrieval_plan_id=retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        selected_search_mode=selected_search_mode,
        selected_runtime_domain=selected_runtime_domain,
        readiness_metadata=readiness_metadata,
    )
    return AssistantRetrievalExecutionRuntimePlan(
        session=build_assistant_retrieval_execution_session(request),
        execution_plan_id=execution_plan_id,
    )


def build_assistant_retrieval_execution_readiness_runtime(
    db: Session,
    *,
    retrieval_plan_id: str,
    organization_id: uuid.UUID | None = None,
    readiness_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = build_assistant_retrieval_execution_gateway(
        db,
        retrieval_plan_id=retrieval_plan_id,
        organization_id=organization_id,
        readiness_metadata=readiness_metadata,
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_retrieval_execution_readiness_schema_version": "1",
            "assistant_retrieval_execution_readiness_prepared": False,
            "assistant_retrieval_execution_gateway": gateway,
            "retrieval_plan_created": False,
            "execution_readiness_created": False,
            "selected_search_mode": gateway.get("selected_search_mode") or "enterprise_search",
            "selected_runtime_domain": gateway.get("selected_runtime_domain") or "enterprise_search",
            "enterprise_search_execution_prepared": False,
            "semantic_search_execution_prepared": False,
            "hybrid_search_execution_prepared": False,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
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
        retrieval_plan_uuid = uuid.UUID(str(retrieval_plan_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    retrieval_plan = repository.get_scoped_artifact(
        AssistantRetrievalPlan,
        AssistantRetrievalPlan.retrieval_plan_id,
        retrieval_plan_uuid,
        organization_id=organization_id,
    )
    if retrieval_plan is None:
        return None
    effective_organization_id = retrieval_plan.organization_id
    assistant = repository.get_scoped_assistant_definition(
        retrieval_plan.assistant_id, organization_id=effective_organization_id
    )
    if assistant is None:
        return None
    session = (
        (
            repository.get_scoped_assistant_session(
                retrieval_plan.assistant_session_id, organization_id=effective_organization_id
            )
            if effective_organization_id is not None
            else repository.get_scoped_artifact(
                AssistantSession,
                AssistantSession.assistant_session_id,
                retrieval_plan.assistant_session_id,
                organization_id=None,
            )
        )
        if retrieval_plan.assistant_session_id
        else None
    )
    if retrieval_plan.assistant_session_id is not None and (
        session is None or session.assistant_id != retrieval_plan.assistant_id
    ):
        return None
    execution_plan = repository.create_assistant_retrieval_execution_plan(
        retrieval_plan_id=retrieval_plan.retrieval_plan_id,
        assistant_id=retrieval_plan.assistant_id,
        assistant_session_id=retrieval_plan.assistant_session_id,
        execution_status="prepared",
        selected_search_mode=retrieval_plan.selected_search_mode,
        selected_runtime_domain=retrieval_plan.selected_runtime_domain,
        execution_state="readiness_only",
        enterprise_search_execution_prepared=retrieval_plan.selected_search_mode == "enterprise_search",
        semantic_search_execution_prepared=False,
        hybrid_search_execution_prepared=False,
        retrieval_executed=False,
        answer_generated=False,
        llm_used=False,
        tool_called=False,
        workflow_executed=False,
        external_action_called=False,
        autonomous_execution=False,
        readiness_metadata={
            **dict(readiness_metadata or {}),
            "assistant_retrieval_execution_readiness_prepared": True,
            "execution_readiness_created": True,
            "retrieval_executed": False,
            "answer_generated": False,
            "llm_used": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    runtime_plan = _runtime_plan(
        retrieval_plan_id=str(retrieval_plan.retrieval_plan_id),
        assistant_id=str(retrieval_plan.assistant_id),
        assistant_session_id=str(retrieval_plan.assistant_session_id) if retrieval_plan.assistant_session_id else None,
        execution_plan_id=str(execution_plan.execution_plan_id),
        selected_search_mode=retrieval_plan.selected_search_mode,
        selected_runtime_domain=retrieval_plan.selected_runtime_domain,
        readiness_metadata=readiness_metadata,
    )
    payload = {
        "assistant_retrieval_execution_readiness_schema_version": "1",
        "assistant_retrieval_execution_readiness_prepared": True,
        "assistant_retrieval_execution_gateway": gateway,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(session) if session is not None else None,
        "assistant_retrieval_plan": assistant_retrieval_plan_to_dict(retrieval_plan),
        "assistant_retrieval_execution_plan": assistant_retrieval_execution_plan_to_dict(execution_plan),
        "assistant_retrieval_execution_runtime_plan": runtime_plan.as_dict(),
        "execution_plan_id": str(execution_plan.execution_plan_id),
        "retrieval_plan_id": str(retrieval_plan.retrieval_plan_id),
        "assistant_id": str(retrieval_plan.assistant_id),
        "assistant_session_id": str(retrieval_plan.assistant_session_id)
        if retrieval_plan.assistant_session_id
        else None,
        "retrieval_plan_created": True,
        "execution_readiness_created": True,
        "execution_status": execution_plan.execution_status,
        "execution_state": execution_plan.execution_state,
        "selected_search_mode": retrieval_plan.selected_search_mode,
        "selected_runtime_domain": retrieval_plan.selected_runtime_domain,
        "enterprise_search_execution_prepared": bool(execution_plan.enterprise_search_execution_prepared),
        "semantic_search_execution_prepared": False,
        "hybrid_search_execution_prepared": False,
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
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
            execution_id=f"assistant-retrieval-execution-readiness:{execution_plan.execution_plan_id}",
            artifact_id=None,
            runtime_outputs={"assistant_retrieval_execution_readiness": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_retrieval_execution_plan(db: Session, execution_plan_id: str) -> dict[str, Any] | None:
    try:
        execution_plan_uuid = uuid.UUID(str(execution_plan_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_assistant_retrieval_execution_plan(execution_plan_uuid)
    return assistant_retrieval_execution_plan_to_dict(record) if record is not None else None


__all__ = [
    "assistant_retrieval_execution_plan_to_dict",
    "build_assistant_retrieval_execution_health",
    "build_assistant_retrieval_execution_readiness_runtime",
    "read_assistant_retrieval_execution_plan",
]
