"""Workflow Runtime session foundation."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.enterprise_search_session import issue, sort_issues
from app.services.workflow_contracts import WorkflowDefinitionRequest, WorkflowSessionDescriptor, WorkflowStepDescriptor

WORKFLOW_STATE_BLOCKED = "blocked"
WORKFLOW_STATE_READY = "ready"
SUPPORTED_RUNTIME_DOMAINS = {
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
    "enterprise_search",
    "runtime_persistence",
    "workflow_runtime",
}
BLOCKED_STEP_TYPES = {
    "external_action",
    "ai",
    "llm",
    "assistant",
    "agent",
    "notification",
    "approval",
    "scheduler",
    "background_worker",
}
BLOCKED_ACTION_TOKENS = {
    "external",
    "webhook",
    "http",
    "api_call",
    "notify",
    "approval",
    "assistant",
    "agent",
    "llm",
    "ai",
    "schedule",
    "worker",
}


def _stable_session_id(*, workflow_key: str, workflow_version: str, step_count: int) -> str | None:
    if not workflow_key:
        return None
    digest = hashlib.sha256(f"{workflow_key}|{workflow_version}|{step_count}|workflow-runtime".encode()).hexdigest()[
        :24
    ]
    return f"workflow-session:{digest}"


def _normalize_key(value: str | None, fallback: str) -> str:
    raw = (value or fallback).strip().lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return normalized or fallback


def build_workflow_definition_request(
    *,
    workflow_name: str | None,
    workflow_key: str | None = None,
    workflow_version: str | None = None,
    workflow_type: str | None = None,
    description: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    requested_by: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> WorkflowDefinitionRequest:
    resolved_name = (workflow_name or "").strip()
    resolved_key = _normalize_key(workflow_key, resolved_name or "workflow")
    descriptors: list[WorkflowStepDescriptor] = []
    for position, item in enumerate(steps or []):
        step = item if isinstance(item, dict) else {}
        step_key = _normalize_key(step.get("step_key"), f"step-{position + 1}")
        descriptors.append(
            WorkflowStepDescriptor(
                step_key=step_key,
                step_name=str(step.get("step_name") or step_key),
                step_order=int(step.get("step_order") if step.get("step_order") is not None else position),
                step_type=str(step.get("step_type") or "runtime_step"),
                step_status=str(step.get("step_status") or "prepared"),
                runtime_domain=str(step.get("runtime_domain") or "workflow_runtime"),
                runtime_action=str(step.get("runtime_action") or "metadata_only"),
                runtime_metadata=dict(
                    step.get("runtime_metadata") if isinstance(step.get("runtime_metadata"), dict) else {}
                ),
            )
        )
    return WorkflowDefinitionRequest(
        workflow_name=resolved_name,
        workflow_key=resolved_key,
        workflow_version=(workflow_version or "1.0").strip() or "1.0",
        workflow_type=(workflow_type or "platform_runtime").strip() or "platform_runtime",
        description=description,
        steps=descriptors,
        requested_by=requested_by,
        runtime_metadata=dict(runtime_metadata or {}),
    )


def build_workflow_session(request: WorkflowDefinitionRequest) -> WorkflowSessionDescriptor:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not request.workflow_name.strip():
        blocking_issues.append(
            issue(
                "workflow_name_missing",
                "Workflow definition requires a generic workflow name.",
                component="workflow_session",
            )
        )
    if not request.workflow_key.strip():
        blocking_issues.append(
            issue("workflow_key_missing", "Workflow definition requires a workflow key.", component="workflow_session")
        )
    if not request.steps:
        blocking_issues.append(
            issue(
                "workflow_steps_missing",
                "Workflow definition requires at least one metadata-only step.",
                component="workflow_session",
            )
        )
    seen_orders: set[int] = set()
    seen_keys: set[str] = set()
    for step in request.steps:
        if step.step_key in seen_keys:
            blocking_issues.append(
                issue(
                    "workflow_step_key_duplicate",
                    "Workflow step keys must be unique.",
                    component="workflow_step",
                    item_id=step.step_key,
                )
            )
        seen_keys.add(step.step_key)
        if step.step_order in seen_orders:
            blocking_issues.append(
                issue(
                    "workflow_step_order_duplicate",
                    "Workflow step order values must be unique.",
                    component="workflow_step",
                    item_id=str(step.step_order),
                )
            )
        seen_orders.add(step.step_order)
        if step.step_order < 0:
            blocking_issues.append(
                issue(
                    "workflow_step_order_invalid",
                    "Workflow step order must be greater than or equal to zero.",
                    component="workflow_step",
                    item_id=step.step_key,
                )
            )
        if step.runtime_domain not in SUPPORTED_RUNTIME_DOMAINS:
            blocking_issues.append(
                issue(
                    "workflow_runtime_domain_unsupported",
                    "Workflow step runtime domain is not supported by metadata-only workflow runtime.",
                    component="workflow_step",
                    item_id=step.runtime_domain,
                )
            )
        if step.step_type.strip().lower() in BLOCKED_STEP_TYPES:
            blocking_issues.append(
                issue(
                    "workflow_step_type_blocked",
                    "Workflow Runtime foundation blocks AI, assistant, scheduler and external action step types.",
                    component="workflow_step",
                    item_id=step.step_type,
                )
            )
        action_tokens = {token for token in re.split(r"[^a-z0-9]+", step.runtime_action.lower()) if token}
        if action_tokens.intersection(BLOCKED_ACTION_TOKENS):
            blocking_issues.append(
                issue(
                    "workflow_runtime_action_blocked",
                    "Workflow Runtime foundation blocks external, AI, assistant, scheduler and background actions.",
                    component="workflow_step",
                    item_id=step.runtime_action,
                )
            )
    ready = not blocking_issues
    return WorkflowSessionDescriptor(
        workflow_session_id=_stable_session_id(
            workflow_key=request.workflow_key, workflow_version=request.workflow_version, step_count=len(request.steps)
        ),
        request=request,
        workflow_state=WORKFLOW_STATE_READY if ready else WORKFLOW_STATE_BLOCKED,
        runtime_metadata={
            **dict(request.runtime_metadata),
            "workflow_runtime_version": "workflow_runtime/1.0",
            "workflow_execution_planned": ready,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "persist_workflow_metadata",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "workflow_session_blocked",
            }
        ],
    )


def serialize_workflow_session(session: WorkflowSessionDescriptor) -> dict[str, Any]:
    return session.as_dict()
