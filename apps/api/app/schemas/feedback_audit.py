import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FeedbackAuditReadiness(BaseModel):
    feedback_center_ready: bool
    audit_explorer_ready: bool
    runtime_explorer_ready: bool
    conversation_history_ready: bool
    assistant_history_ready: bool
    search_history_ready: bool
    document_lifecycle_history_ready: bool
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)


class FeedbackCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    target_type: str = Field(default="runtime", min_length=1, max_length=128)
    target_id: str | None = Field(default=None, max_length=255)
    rating: str = Field(default="neutral", min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)
    actor_type: str | None = Field(default="user", max_length=64)
    actor_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    target_type: str | None = None
    target_id: str | None = None
    rating: str | None = None
    comment_recorded: bool
    actor_type: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    feedback_persisted: bool = True
    postgresql_source_of_truth: bool = True


class ExplorerItem(BaseModel):
    id: str
    type: str
    created_at: str | None = None
    status: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExplorerListResponse(BaseModel):
    items: list[ExplorerItem]
    count: int
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False
