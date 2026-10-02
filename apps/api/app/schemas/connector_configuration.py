from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_REFERENCE_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")


class ConnectorCredentialReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolver_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    reference: str = Field(min_length=1, max_length=1024)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not SAFE_REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("credential reference must be an opaque external resolver key")
        return normalized


class ConnectorConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_type_id: uuid.UUID
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)
    credential: ConnectorCredentialReferenceInput | None = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConnectorConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    configuration: dict[str, Any] | None = None
    credential: ConnectorCredentialReferenceInput | None = None
    clear_credential: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_credential_change(self) -> ConnectorConfigurationUpdate:
        if self.credential is not None and self.clear_credential:
            raise ValueError("credential and clear_credential cannot be supplied together")
        return self


class ConnectorEnabledStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    enabled: bool


class ConnectorLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)


class ConnectorConfigurationRead(BaseModel):
    id: uuid.UUID
    connector_type_id: uuid.UUID
    code: str
    name: str
    status: str
    enabled: bool
    lifecycle_status: Literal["active", "archived"]
    configuration_version: int
    configuration: dict[str, Any] = Field(default_factory=dict)
    configuration_status: Literal["valid", "legacy_requires_review"]
    credential_configured: bool
    credential_resolver_type: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
