import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class OrganizationUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class OrganizationRead(OrganizationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class OrganizationDeletionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    requested_by: str | None = Field(default=None, max_length=255)


class OrganizationDeletionExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deletion_execution_id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    requested_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    resource_counts_before: dict[str, int] = Field(default_factory=dict)
    resource_counts_deleted: dict[str, int] = Field(default_factory=dict)
    object_storage_objects_deleted: int = 0
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
    correlation_id: str
    external_objects: list[dict[str, Any]] = Field(default_factory=list)
    estimated_operations: int = 0
    replayed: bool = False


class OrganizationNodeCreate(BaseModel):
    organization_id: uuid.UUID
    parent_node_id: uuid.UUID | None = None
    node_type: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class OrganizationNodeUpdate(BaseModel):
    parent_node_id: uuid.UUID | None = None
    node_type: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] | None = None
    position: dict[str, Any] | None = None
    status: str | None = None


class OrganizationNodeRead(OrganizationNodeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class OrganizationRelationshipCreate(BaseModel):
    organization_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relationship_type: str = Field(min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class OrganizationRelationshipUpdate(BaseModel):
    source_node_id: uuid.UUID | None = None
    target_node_id: uuid.UUID | None = None
    relationship_type: str | None = Field(default=None, min_length=1, max_length=64)
    metadata: dict[str, Any] | None = None
    status: str | None = None


class OrganizationRelationshipRead(OrganizationRelationshipCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
