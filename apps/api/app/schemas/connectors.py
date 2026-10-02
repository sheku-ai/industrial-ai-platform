import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    edition: str = "community"
    connector_kind: str = Field(min_length=1, max_length=64)
    description: str | None = None
    config_schema: dict[str, Any] = Field(default_factory=dict)
    status: str = "available"


class ConnectorTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    edition: str | None = None
    connector_kind: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    config_schema: dict[str, Any] | None = None
    status: str | None = None


class ConnectorTypeRead(ConnectorTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ConnectorCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    connector_type_id: uuid.UUID
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class ConnectorUpdate(BaseModel):
    connector_type_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    status: str | None = None


class ConnectorRead(ConnectorCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ConnectorConfigCreate(BaseModel):
    connector_id: uuid.UUID
    version: int = 1
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ConnectorConfigUpdate(BaseModel):
    version: int | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class ConnectorConfigRead(ConnectorConfigCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ConnectorRunCreate(BaseModel):
    connector_id: uuid.UUID
    run_status: str = "pending"
    summary: dict[str, Any] = Field(default_factory=dict)


class ConnectorRunUpdate(BaseModel):
    run_status: str | None = None
    summary: dict[str, Any] | None = None


class ConnectorRunRead(ConnectorRunCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
