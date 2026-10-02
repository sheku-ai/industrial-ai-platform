from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RuntimeWorkerEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_type: str | None
    actor_id: str | None
    resource_type: str | None
    resource_id: str | None
    summary: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class RuntimeWorkerHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: str
    action: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    actor_type: str | None
    actor_id: str | None
    created_at: datetime
