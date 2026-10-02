from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssistantCreateRequest(BaseModel):
    assistant_name: str = Field(min_length=1, max_length=255)
    assistant_key: str | None = Field(default=None, max_length=128)
    assistant_version: str | None = Field(default="1.0", max_length=64)
    assistant_type: str | None = Field(default="platform_assistant", max_length=128)
    description: str | None = None
    default_search_mode: str | None = Field(default="enterprise_search", max_length=64)
    allowed_runtime_domains: list[str] = Field(default_factory=lambda: ["enterprise_search"])
    guardrail_profile: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=255)
    conversation_reference: str | None = Field(default=None, max_length=255)
    requested_query: str | None = Field(default=None, max_length=2048)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantSessionCreateRequest(BaseModel):
    requested_by: str | None = Field(default=None, max_length=255)
    conversation_reference: str | None = Field(default=None, max_length=255)
    runtime_context: dict[str, Any] = Field(default_factory=dict)


class AssistantSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantRunCreateRequest(BaseModel):
    assistant_session_id: str | None = Field(default=None, max_length=128)
    requested_query: str | None = Field(default=None, max_length=2048)
    selected_search_mode: str | None = Field(default=None, max_length=64)
    selected_runtime_domain: str | None = Field(default=None, max_length=64)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantRetrievalPlanCreateRequest(BaseModel):
    assistant_session_id: str | None = Field(default=None, max_length=128)
    requested_query: str | None = Field(default=None, max_length=2048)
    selected_search_mode: str | None = Field(default="enterprise_search", max_length=64)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantRetrievalPlanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantRetrievalPlanHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantRetrievalExecutionReadinessCreateRequest(BaseModel):
    readiness_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantRetrievalExecutionReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantRetrievalExecutionReadinessHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantSearchExecutionCreateRequest(BaseModel):
    top_k: int | None = Field(default=10, ge=1, le=50)
    search_config: dict[str, Any] = Field(default_factory=dict)


class AssistantSearchExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantSearchExecutionHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantContextBuilderCreateRequest(BaseModel):
    package_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantContextPackageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantContextBuilderHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantPromptAssemblyCreateRequest(BaseModel):
    prompt_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantPromptPackageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantPromptAssemblyHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantLlmGatewayCreateRequest(BaseModel):
    provider_type: str = Field(default="reference", min_length=1, max_length=64)
    provider_name: str = Field(default="metadata-only", min_length=1, max_length=128)
    model_name: str = Field(default="metadata-only", min_length=1, max_length=128)
    planned_temperature: float = Field(default=0.0, ge=0.0)
    planned_max_tokens: int = Field(default=1024, ge=1)
    planned_top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    planned_stop_sequences: list[str] = Field(default_factory=list)
    planned_seed: int | None = None
    planned_timeout: int = Field(default=30, ge=1)
    gateway_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantLlmGatewayResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantLlmGatewayHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantLlmExecutionCreateRequest(BaseModel):
    request_payload_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantLlmExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantLlmExecutionHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantCitationVerificationCreateRequest(BaseModel):
    request_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantCitationVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantCitationVerificationHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantResponseCreateRequest(BaseModel):
    response_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantResponseResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantResponseHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConversationCreateRequest(BaseModel):
    assistant_id: str | None = Field(default=None, max_length=128)
    assistant_session_id: str | None = Field(default=None, max_length=128)
    conversation_title: str | None = Field(default=None, max_length=255)
    conversation_reference: str | None = Field(default=None, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    conversation_metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConversationHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConversationTurnCreateRequest(BaseModel):
    turn_role: str = Field(min_length=1, max_length=32)
    input_text: str | None = None
    output_text: str | None = None
    assistant_run_id: str | None = Field(default=None, max_length=128)
    response_format: str = Field(default="markdown", max_length=64)
    citation_summary: dict[str, Any] = Field(default_factory=dict)
    ordered_citations: list[dict[str, Any]] = Field(default_factory=list)
    turn_metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationTurnResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantChatRequest(BaseModel):
    assistant_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1)
    requested_by: str | None = Field(default=None, max_length=255)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantChatHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
