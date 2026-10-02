from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStepRequest(BaseModel):
    step_key: str = Field(min_length=1, max_length=128)
    step_name: str = Field(min_length=1, max_length=255)
    step_order: int = Field(ge=0)
    step_type: str = Field(default="runtime_step", min_length=1, max_length=128)
    step_status: str = Field(default="prepared", max_length=32)
    runtime_domain: str = Field(default="workflow_runtime", min_length=1, max_length=64)
    runtime_action: str = Field(default="metadata_only", min_length=1, max_length=128)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateRequest(BaseModel):
    workflow_name: str = Field(min_length=1, max_length=255)
    workflow_key: str | None = Field(default=None, max_length=128)
    workflow_version: str | None = Field(default="1.0", max_length=64)
    workflow_type: str | None = Field(default="platform_runtime", max_length=128)
    description: str | None = None
    steps: list[WorkflowStepRequest] = Field(default_factory=list)
    requested_by: str | None = Field(default=None, max_length=255)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class WorkflowStepResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class WorkflowRunCreateRequest(BaseModel):
    requested_by: str | None = Field(default=None, max_length=255)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class WorkflowHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
