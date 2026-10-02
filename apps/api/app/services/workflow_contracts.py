"""Metadata-only Workflow Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowStepDescriptor:
    step_key: str
    step_name: str
    step_order: int
    step_type: str
    runtime_domain: str
    runtime_action: str
    step_status: str = "prepared"
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_step_descriptor_schema_version": "1",
            "step_key": self.step_key,
            "step_name": self.step_name,
            "step_order": self.step_order,
            "step_type": self.step_type,
            "step_status": self.step_status,
            "runtime_domain": self.runtime_domain,
            "runtime_action": self.runtime_action,
            "runtime_metadata": dict(self.runtime_metadata),
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
        }


@dataclass(frozen=True)
class WorkflowDefinitionRequest:
    workflow_name: str
    workflow_key: str
    workflow_version: str = "1.0"
    workflow_type: str = "platform_runtime"
    description: str | None = None
    steps: list[WorkflowStepDescriptor] = field(default_factory=list)
    requested_by: str | None = None
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_definition_request_schema_version": "1",
            "workflow_name": self.workflow_name,
            "workflow_key": self.workflow_key,
            "workflow_version": self.workflow_version,
            "workflow_type": self.workflow_type,
            "description": self.description,
            "steps": [step.as_dict() for step in self.steps],
            "requested_by": self.requested_by,
            "runtime_metadata": dict(self.runtime_metadata),
        }


@dataclass(frozen=True)
class WorkflowSessionDescriptor:
    workflow_session_id: str | None
    request: WorkflowDefinitionRequest
    workflow_state: str
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        ready = self.workflow_state == "ready"
        return {
            "workflow_session_schema_version": "1",
            "workflow_session_id": self.workflow_session_id,
            "workflow_session_ready": ready,
            "workflow_state": self.workflow_state,
            "request": self.request.as_dict(),
            "workflow_name": self.request.workflow_name,
            "workflow_key": self.request.workflow_key,
            "workflow_version": self.request.workflow_version,
            "workflow_type": self.request.workflow_type,
            "step_count": len(self.request.steps),
            "runtime_metadata": dict(self.runtime_metadata),
            "workflow_runtime_prepared": ready,
            "workflow_execution_planned": ready,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "next_available_actions": list(self.next_available_actions),
        }


@dataclass(frozen=True)
class WorkflowExecutionPlan:
    session: WorkflowSessionDescriptor
    workflow_id: str | None
    workflow_run_id: str | None
    execution_allowed: bool = False
    descriptor_only: bool = True
    workflow_execution_planned: bool = True
    workflow_executed: bool = False
    external_action_called: bool = False
    ai_used: bool = False
    llm_used: bool = False
    assistant_used: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_execution_plan_schema_version": "1",
            "session": self.session.as_dict(),
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.workflow_run_id,
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "workflow_execution_planned": self.workflow_execution_planned,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "ai_used": self.ai_used,
            "llm_used": self.llm_used,
            "assistant_used": self.assistant_used,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }


@dataclass(frozen=True)
class WorkflowRuntimeResult:
    execution_plan: WorkflowExecutionPlan
    workflow_status: str
    run_status: str
    workflow_definition_created: bool
    workflow_steps_created: bool
    workflow_run_created: bool
    step_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_runtime_result_schema_version": "1",
            "workflow_status": self.workflow_status,
            "run_status": self.run_status,
            "workflow_definition_created": self.workflow_definition_created,
            "workflow_steps_created": self.workflow_steps_created,
            "workflow_run_created": self.workflow_run_created,
            "step_count": self.step_count,
            "workflow_execution_planned": True,
            "workflow_executed": False,
            "external_action_called": False,
            "ai_used": False,
            "llm_used": False,
            "assistant_used": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "execution_plan": self.execution_plan.as_dict(),
        }


@dataclass(frozen=True)
class WorkflowHealthResult:
    workflow_runtime_available: bool = True
    workflow_runtime_status: str = "metadata_only"
    workflow_executed: bool = False
    external_action_called: bool = False
    ai_used: bool = False
    llm_used: bool = False
    assistant_used: bool = False
    autonomous_execution: bool = False
    postgresql_source_of_truth: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_health_schema_version": "1",
            "workflow_runtime_available": self.workflow_runtime_available,
            "workflow_runtime_status": self.workflow_runtime_status,
            "workflow_executed": self.workflow_executed,
            "external_action_called": self.external_action_called,
            "ai_used": self.ai_used,
            "llm_used": self.llm_used,
            "assistant_used": self.assistant_used,
            "autonomous_execution": self.autonomous_execution,
            "postgresql_source_of_truth": self.postgresql_source_of_truth,
        }
