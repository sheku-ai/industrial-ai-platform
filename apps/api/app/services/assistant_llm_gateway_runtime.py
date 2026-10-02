"""Assistant LLM Gateway runtime."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantLlmInvocationPlan, AssistantPromptPackage
from app.repositories.assistant import AssistantRepository
from app.services.assistant_llm_gateway_gateway import build_assistant_llm_gateway, build_assistant_llm_gateway_health


def assistant_llm_invocation_plan_to_dict(record: AssistantLlmInvocationPlan) -> dict[str, Any]:
    return {
        "gateway_id": str(record.gateway_id),
        "prompt_package_id": str(record.prompt_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "provider_type": record.provider_type,
        "provider_name": record.provider_name,
        "model_name": record.model_name,
        "provider_ready": bool(record.provider_ready),
        "execution_allowed": bool(record.execution_allowed),
        "blocked_reason": record.blocked_reason,
        "planned_temperature": float(record.planned_temperature or 0.0),
        "planned_max_tokens": int(record.planned_max_tokens or 0),
        "planned_top_p": float(record.planned_top_p or 0.0),
        "planned_stop_sequences": list(record.planned_stop_sequences or []),
        "planned_seed": record.planned_seed,
        "planned_timeout": int(record.planned_timeout or 0),
        "llm_invoked": bool(record.llm_invoked),
        "answer_generated": bool(record.answer_generated),
        "tool_execution": bool(record.tool_execution),
        "tool_called": bool(record.tool_execution),
        "workflow_execution": bool(record.workflow_execution),
        "workflow_executed": bool(record.workflow_execution),
        "external_action_called": bool(record.external_action_called),
        "autonomous_execution": bool(record.autonomous_execution),
        "gateway_metadata": record.gateway_metadata or {},
        "assistant_llm_gateway_prepared": True,
        "prompt_package_created": True,
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def build_assistant_llm_gateway_runtime(
    db: Session,
    *,
    prompt_package_id: str,
    organization_id: uuid.UUID | None = None,
    provider_type: str = "reference",
    provider_name: str = "metadata-only",
    model_name: str = "metadata-only",
    planned_temperature: float = 0.0,
    planned_max_tokens: int = 1024,
    planned_top_p: float = 1.0,
    planned_stop_sequences: list[str] | None = None,
    planned_seed: int | None = None,
    planned_timeout: int = 30,
    gateway_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    scoped_repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(prompt_package_id))
    except (TypeError, ValueError):
        return None
    scoped_artifact = scoped_repository.get_scoped_artifact(
        AssistantPromptPackage,
        AssistantPromptPackage.prompt_package_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if scoped_artifact is None or (scoped_artifact.ownership_scope == "organization" and organization_id is None):
        return None
    gateway = build_assistant_llm_gateway(
        db,
        prompt_package_id=prompt_package_id,
        provider_type=provider_type,
        provider_name=provider_name,
        model_name=model_name,
        planned_temperature=planned_temperature,
        planned_max_tokens=planned_max_tokens,
        planned_top_p=planned_top_p,
        planned_stop_sequences=planned_stop_sequences,
        planned_seed=planned_seed,
        planned_timeout=planned_timeout,
        gateway_metadata=gateway_metadata,
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_llm_gateway_schema_version": "1",
            "assistant_llm_gateway_prepared": False,
            "assistant_llm_gateway": gateway,
            "prompt_package_created": bool(gateway.get("prompt_package_created")),
            "provider_ready": True,
            "execution_allowed": False,
            "blocked_reason": "execution_disabled",
            "llm_invoked": False,
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
    repository = AssistantRepository(db)
    prompt_package = scoped_artifact
    if prompt_package is None:
        return None
    llm_plan = repository.create_llm_invocation_plan(
        prompt_package_id=prompt_package.prompt_package_id,
        assistant_id=prompt_package.assistant_id,
        assistant_session_id=prompt_package.assistant_session_id,
        provider_type=str(provider_type or "reference"),
        provider_name=str(provider_name or "metadata-only"),
        model_name=str(model_name or "metadata-only"),
        provider_ready=True,
        execution_allowed=False,
        blocked_reason="execution_disabled",
        planned_temperature=planned_temperature,
        planned_max_tokens=planned_max_tokens,
        planned_top_p=planned_top_p,
        planned_stop_sequences=planned_stop_sequences,
        planned_seed=planned_seed,
        planned_timeout=planned_timeout,
        llm_invoked=False,
        answer_generated=False,
        tool_execution=False,
        workflow_execution=False,
        external_action_called=False,
        autonomous_execution=False,
        gateway_metadata={
            **dict(gateway_metadata or {}),
            "assistant_llm_gateway_prepared": True,
            "prompt_package_created": True,
            "provider_ready": True,
            "execution_allowed": False,
            "blocked_reason": "execution_disabled",
            "llm_invoked": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
    )
    db.commit()
    payload = {
        "assistant_llm_gateway_schema_version": "1",
        "assistant_llm_gateway_prepared": True,
        "assistant_llm_gateway": gateway,
        "assistant_llm_invocation_plan": assistant_llm_invocation_plan_to_dict(llm_plan),
        "gateway_id": str(llm_plan.gateway_id),
        "prompt_package_id": str(prompt_package.prompt_package_id),
        "assistant_id": str(prompt_package.assistant_id),
        "assistant_session_id": str(prompt_package.assistant_session_id)
        if prompt_package.assistant_session_id
        else None,
        "provider_type": llm_plan.provider_type,
        "provider_name": llm_plan.provider_name,
        "model_name": llm_plan.model_name,
        "provider_ready": True,
        "execution_allowed": False,
        "blocked_reason": "execution_disabled",
        "planned_temperature": float(llm_plan.planned_temperature or 0.0),
        "planned_max_tokens": int(llm_plan.planned_max_tokens or 0),
        "planned_top_p": float(llm_plan.planned_top_p or 0.0),
        "planned_stop_sequences": list(llm_plan.planned_stop_sequences or []),
        "planned_seed": llm_plan.planned_seed,
        "planned_timeout": int(llm_plan.planned_timeout or 0),
        "prompt_package_created": True,
        "llm_invoked": False,
        "answer_generated": False,
        "tool_execution": False,
        "tool_called": False,
        "workflow_execution": False,
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
            execution_id=f"assistant-llm-gateway:{llm_plan.gateway_id}",
            artifact_id=None,
            runtime_outputs={"assistant_llm_gateway": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_llm_gateway(db: Session, gateway_id: str) -> dict[str, Any] | None:
    try:
        gateway_uuid = uuid.UUID(str(gateway_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_llm_invocation_plan(gateway_uuid)
    return assistant_llm_invocation_plan_to_dict(record) if record is not None else None


__all__ = [
    "assistant_llm_invocation_plan_to_dict",
    "build_assistant_llm_gateway_health",
    "build_assistant_llm_gateway_runtime",
    "read_assistant_llm_gateway",
]
