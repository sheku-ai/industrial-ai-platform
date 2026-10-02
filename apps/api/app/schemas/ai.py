import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    provider_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    adapter_type: str = Field(min_length=1, max_length=128)
    provider_type: str = Field(min_length=1, max_length=128)
    status: str = "draft"
    enabled: bool = False
    configuration: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    health_state: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class ProviderUpdate(BaseModel):
    provider_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    adapter_type: str | None = Field(default=None, min_length=1, max_length=128)
    provider_type: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = None
    enabled: bool | None = None
    configuration: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None
    health_state: str | None = None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class ProviderRead(ProviderCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ModelCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=255)
    endpoint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "available"

    provider_id: uuid.UUID | None = None
    model_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    model_ref: str | None = Field(default=None, min_length=1, max_length=255)
    model_type: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    context_window: int | None = None
    enabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class ModelUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None

    provider_id: uuid.UUID | None = None
    model_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    model_ref: str | None = Field(default=None, min_length=1, max_length=255)
    model_type: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None
    context_window: int | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class ModelRead(ModelCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class PromptCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    content: str
    variables: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"

    prompt_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    prompt_type: str | None = Field(default=None, min_length=1, max_length=128)
    template: str | None = None
    template_format: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool = False
    version: str | None = Field(default=None, min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class PromptUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    variables: dict[str, Any] | None = None
    status: str | None = None

    prompt_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    prompt_type: str | None = Field(default=None, min_length=1, max_length=128)
    template: str | None = None
    template_format: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None
    version: str | None = Field(default=None, min_length=1, max_length=64)
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class PromptRead(PromptCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class AgentCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class AgentUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


class AgentRead(AgentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class KnowledgeSourceCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class KnowledgeSourceUpdate(BaseModel):
    agent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


class KnowledgeSourceRead(KnowledgeSourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class RuleCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    rules: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"

    guardrail_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    guardrail_type: str | None = Field(default=None, min_length=1, max_length=128)
    policy: dict[str, Any] = Field(default_factory=dict)
    enforcement_mode: str | None = Field(default=None, min_length=1, max_length=64)
    fallback_behavior: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class RuleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    rules: dict[str, Any] | None = None
    status: str | None = None

    guardrail_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    guardrail_type: str | None = Field(default=None, min_length=1, max_length=128)
    policy: dict[str, Any] | None = None
    enforcement_mode: str | None = Field(default=None, min_length=1, max_length=64)
    fallback_behavior: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class RuleRead(RuleCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class WorkflowCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    definition: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class WorkflowUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    definition: dict[str, Any] | None = None
    status: str | None = None


class WorkflowRead(WorkflowCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class RuntimeProfileCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    profile_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    answer_mode: str = Field(min_length=1, max_length=64)
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    guardrail_id: uuid.UUID | None = None
    generation_enabled: bool = False
    fallback_mode: str | None = Field(default=None, min_length=1, max_length=64)
    configuration: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class RuntimeProfileUpdate(BaseModel):
    profile_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    answer_mode: str | None = Field(default=None, min_length=1, max_length=64)
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    guardrail_id: uuid.UUID | None = None
    generation_enabled: bool | None = None
    fallback_mode: str | None = Field(default=None, min_length=1, max_length=64)
    configuration: dict[str, Any] | None = None
    status: str | None = None
    is_default: bool | None = None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_json")


class RuntimeProfileRead(RuntimeProfileCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
