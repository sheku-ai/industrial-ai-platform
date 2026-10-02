"""Metadata-only Assistant Runtime foundation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantDefinition, AssistantRuntimeRun, AssistantSession
from app.repositories.assistant import AssistantRepository
from app.services.assistant_contracts import AssistantRuntimePlan, AssistantRuntimeResult
from app.services.assistant_gateway import build_assistant_gateway, build_assistant_health
from app.services.assistant_session import (
    SEARCH_MODE_RUNTIME_DOMAIN,
    SUPPORTED_RUNTIME_DOMAINS,
    SUPPORTED_SEARCH_MODES,
    build_assistant_definition_request,
    build_assistant_session,
)


def assistant_to_dict(record: AssistantDefinition) -> dict[str, Any]:
    return {
        "assistant_id": str(record.assistant_id),
        "organization_id": str(record.organization_id) if record.organization_id else None,
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "assistant_key": record.assistant_key,
        "assistant_name": record.assistant_name,
        "assistant_status": record.assistant_status,
        "assistant_version": record.assistant_version,
        "assistant_type": record.assistant_type,
        "description": record.description,
        "default_search_mode": record.default_search_mode,
        "allowed_runtime_domains": list(record.allowed_runtime_domains or []),
        "guardrail_profile": record.guardrail_profile or {},
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def assistant_session_to_dict(record: AssistantSession) -> dict[str, Any]:
    return {
        "assistant_session_id": str(record.assistant_session_id),
        "assistant_id": str(record.assistant_id),
        "session_status": record.session_status,
        "requested_by": record.requested_by,
        "conversation_reference": record.conversation_reference,
        "runtime_context": record.runtime_context or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def assistant_run_to_dict(record: AssistantRuntimeRun) -> dict[str, Any]:
    return {
        "assistant_run_id": str(record.assistant_run_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id),
        "run_status": record.run_status,
        "requested_query": record.requested_query,
        "selected_search_mode": record.selected_search_mode,
        "selected_runtime_domain": record.selected_runtime_domain,
        "execution_state": record.execution_state,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "failed_at": record.failed_at.isoformat() if record.failed_at else None,
        "failure_reason": record.failure_reason,
        "runtime_metadata": record.runtime_metadata or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _runtime_plan(
    session_payload: dict[str, Any],
    assistant_id: str | None,
    assistant_session_id: str | None,
    assistant_run_id: str | None,
) -> AssistantRuntimePlan:
    request_payload = session_payload.get("request") if isinstance(session_payload.get("request"), dict) else {}
    request = build_assistant_definition_request(
        assistant_name=request_payload.get("assistant_name"),
        assistant_key=request_payload.get("assistant_key"),
        assistant_version=request_payload.get("assistant_version"),
        assistant_type=request_payload.get("assistant_type"),
        description=request_payload.get("description"),
        default_search_mode=request_payload.get("default_search_mode"),
        allowed_runtime_domains=request_payload.get("allowed_runtime_domains")
        if isinstance(request_payload.get("allowed_runtime_domains"), list)
        else [],
        guardrail_profile=request_payload.get("guardrail_profile")
        if isinstance(request_payload.get("guardrail_profile"), dict)
        else {},
        requested_by=request_payload.get("requested_by"),
        conversation_reference=request_payload.get("conversation_reference"),
        requested_query=request_payload.get("requested_query"),
        runtime_context=request_payload.get("runtime_context")
        if isinstance(request_payload.get("runtime_context"), dict)
        else {},
        runtime_metadata=request_payload.get("runtime_metadata")
        if isinstance(request_payload.get("runtime_metadata"), dict)
        else {},
    )
    return AssistantRuntimePlan(
        session=build_assistant_session(request),
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        assistant_run_id=assistant_run_id,
    )


def build_assistant_runtime(
    db: Session,
    *,
    assistant_name: str,
    assistant_key: str | None = None,
    assistant_version: str | None = None,
    assistant_type: str | None = None,
    description: str | None = None,
    default_search_mode: str | None = None,
    allowed_runtime_domains: list[str] | None = None,
    guardrail_profile: dict[str, Any] | None = None,
    requested_by: str | None = None,
    conversation_reference: str | None = None,
    requested_query: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    organization_id: uuid.UUID | None,
    ownership_scope: str,
    data_origin: str,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = build_assistant_gateway(
        db,
        assistant_name=assistant_name,
        assistant_key=assistant_key,
        assistant_version=assistant_version,
        assistant_type=assistant_type,
        description=description,
        default_search_mode=default_search_mode,
        allowed_runtime_domains=allowed_runtime_domains,
        guardrail_profile=guardrail_profile,
        requested_by=requested_by,
        conversation_reference=conversation_reference,
        requested_query=requested_query,
        runtime_context=runtime_context,
        runtime_metadata=runtime_metadata,
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_runtime_schema_version": "1",
            "assistant_runtime_prepared": False,
            "assistant_gateway": gateway,
            "assistant_definition_created": False,
            "assistant_session_created": False,
            "assistant_run_created": False,
            "assistant_execution_planned": False,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = AssistantRepository(db)
    session_payload = gateway.get("assistant_session") if isinstance(gateway.get("assistant_session"), dict) else {}
    request = session_payload.get("request") if isinstance(session_payload.get("request"), dict) else {}
    assistant, inserted = repository.create_assistant_definition(
        organization_id=organization_id,
        ownership_scope=ownership_scope,
        data_origin=data_origin,
        assistant_key=str(request.get("assistant_key")),
        assistant_name=str(request.get("assistant_name")),
        assistant_status="prepared",
        assistant_version=str(request.get("assistant_version") or "1.0"),
        assistant_type=str(request.get("assistant_type") or "platform_assistant"),
        description=request.get("description"),
        default_search_mode=str(request.get("default_search_mode") or "enterprise_search"),
        allowed_runtime_domains=list(request.get("allowed_runtime_domains") or []),
        guardrail_profile=request.get("guardrail_profile")
        if isinstance(request.get("guardrail_profile"), dict)
        else {},
        runtime_metadata={
            **(
                session_payload.get("runtime_metadata")
                if isinstance(session_payload.get("runtime_metadata"), dict)
                else {}
            ),
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
        },
    )
    assistant_session = repository.create_assistant_session(
        assistant_id=assistant.assistant_id,
        session_status="prepared",
        requested_by=request.get("requested_by"),
        conversation_reference=request.get("conversation_reference"),
        runtime_context=request.get("runtime_context") if isinstance(request.get("runtime_context"), dict) else {},
    )
    selected_search_mode = str(session_payload.get("selected_search_mode") or assistant.default_search_mode)
    selected_runtime_domain = str(session_payload.get("selected_runtime_domain") or "enterprise_search")
    assistant_run = repository.create_assistant_runtime_run(
        assistant_id=assistant.assistant_id,
        assistant_session_id=assistant_session.assistant_session_id,
        run_status="planned",
        requested_query=request.get("requested_query"),
        selected_search_mode=selected_search_mode,
        selected_runtime_domain=selected_runtime_domain,
        execution_state="metadata_only",
        runtime_metadata={
            "assistant_execution_planned": True,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    plan = _runtime_plan(
        session_payload,
        str(assistant.assistant_id),
        str(assistant_session.assistant_session_id),
        str(assistant_run.assistant_run_id),
    )
    result = AssistantRuntimeResult(
        runtime_plan=plan,
        assistant_status=assistant.assistant_status,
        session_status=assistant_session.session_status,
        run_status=assistant_run.run_status,
        assistant_definition_created=True,
        assistant_session_created=True,
        assistant_run_created=True,
    )
    payload = {
        "assistant_runtime_schema_version": "1",
        "assistant_runtime_prepared": True,
        "assistant_gateway": gateway,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(assistant_session),
        "assistant_run": assistant_run_to_dict(assistant_run),
        "assistant_runtime_plan": plan.as_dict(),
        "assistant_runtime_result": result.as_dict(),
        "assistant_id": str(assistant.assistant_id),
        "assistant_session_id": str(assistant_session.assistant_session_id),
        "assistant_run_id": str(assistant_run.assistant_run_id),
        "assistant_status": assistant.assistant_status,
        "session_status": assistant_session.session_status,
        "run_status": assistant_run.run_status,
        "selected_search_mode": selected_search_mode,
        "selected_runtime_domain": selected_runtime_domain,
        "assistant_definition_created": True,
        "assistant_definition_inserted": inserted,
        "assistant_session_created": True,
        "assistant_run_created": True,
        "assistant_execution_planned": True,
        "assistant_executed": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "enterprise_search_used": False,
        "hybrid_search_used": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-runtime:{assistant_run.assistant_run_id}",
            artifact_id=None,
            runtime_outputs={"assistant_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def build_assistant_session_runtime(
    db: Session,
    *,
    assistant_id: str,
    organization_id: uuid.UUID | None = None,
    requested_by: str | None = None,
    conversation_reference: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    assistant = repository.get_scoped_assistant_definition(assistant_uuid, organization_id=organization_id)
    if assistant is None:
        return None
    session = repository.create_assistant_session(
        assistant_id=assistant.assistant_id,
        execution_organization_id=organization_id,
        session_status="prepared",
        requested_by=requested_by,
        conversation_reference=conversation_reference,
        runtime_context=runtime_context,
    )
    db.commit()
    return assistant_session_to_dict(session)


def build_assistant_run_runtime(
    db: Session,
    *,
    assistant_id: str,
    assistant_session_id: str | None = None,
    organization_id: uuid.UUID | None = None,
    requested_query: str | None = None,
    selected_search_mode: str | None = None,
    selected_runtime_domain: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
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
        if session is None:
            return None
        if session.assistant_id != assistant.assistant_id:
            return None
    else:
        session = repository.create_assistant_session(
            assistant_id=assistant.assistant_id, execution_organization_id=organization_id
        )
    search_mode = (
        selected_search_mode if selected_search_mode in SUPPORTED_SEARCH_MODES else assistant.default_search_mode
    )
    runtime_domain = (
        selected_runtime_domain
        if selected_runtime_domain in SUPPORTED_RUNTIME_DOMAINS
        else SEARCH_MODE_RUNTIME_DOMAIN.get(search_mode, "enterprise_search")
    )
    if runtime_domain == "assistant_runtime":
        runtime_domain = "enterprise_search"
    run = repository.create_assistant_runtime_run(
        assistant_id=assistant.assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
        requested_query=requested_query,
        selected_search_mode=search_mode,
        selected_runtime_domain=runtime_domain,
        runtime_metadata={
            **dict(runtime_metadata or {}),
            "assistant_execution_planned": True,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    payload = {
        "assistant_runtime_schema_version": "1",
        "assistant_runtime_prepared": True,
        "assistant": assistant_to_dict(assistant),
        "assistant_session": assistant_session_to_dict(session),
        "assistant_run": assistant_run_to_dict(run),
        "assistant_id": str(assistant.assistant_id),
        "assistant_session_id": str(session.assistant_session_id),
        "assistant_run_id": str(run.assistant_run_id),
        "assistant_status": assistant.assistant_status,
        "session_status": session.session_status,
        "run_status": run.run_status,
        "selected_search_mode": search_mode,
        "selected_runtime_domain": runtime_domain,
        "assistant_definition_created": False,
        "assistant_session_created": assistant_session_id is None,
        "assistant_run_created": True,
        "assistant_execution_planned": True,
        "assistant_executed": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "enterprise_search_used": False,
        "hybrid_search_used": False,
        "postgresql_source_of_truth": True,
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-runtime:{run.assistant_run_id}",
            artifact_id=None,
            runtime_outputs={"assistant_runtime": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant(
    db: Session,
    assistant_id: str,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool = False,
) -> dict[str, Any] | None:
    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_scoped_assistant_definition(
        assistant_uuid, organization_id=organization_id, platform_scope=platform_scope
    )
    return assistant_to_dict(record) if record is not None else None


def list_assistants_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool = False,
    assistant_status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    records = AssistantRepository(db).list_scoped_assistant_definitions(
        organization_id=organization_id,
        platform_scope=platform_scope,
        assistant_status=assistant_status,
        limit=limit,
    )
    return {
        "assistant_list_schema_version": "1",
        "assistant_count": len(records),
        "assistants": [assistant_to_dict(record) for record in records],
        "postgresql_source_of_truth": True,
    }


def read_assistant_session(db: Session, assistant_session_id: str) -> dict[str, Any] | None:
    try:
        session_uuid = uuid.UUID(str(assistant_session_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_assistant_session(session_uuid)
    return assistant_session_to_dict(record) if record is not None else None


def read_assistant_run(db: Session, assistant_run_id: str) -> dict[str, Any] | None:
    try:
        run_uuid = uuid.UUID(str(assistant_run_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_assistant_runtime_run(run_uuid)
    return assistant_run_to_dict(record) if record is not None else None


__all__ = [
    "build_assistant_health",
    "build_assistant_run_runtime",
    "build_assistant_runtime",
    "build_assistant_session_runtime",
    "list_assistants_runtime",
    "read_assistant",
    "read_assistant_run",
    "read_assistant_session",
]
