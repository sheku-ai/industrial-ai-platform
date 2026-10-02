from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReconciliationStatus = Literal[
    "reserved",
    "publishing",
    "published",
    "missing",
    "checksum_conflict",
]


class ReconciliationBatchRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=100)
    statuses: list[ReconciliationStatus] | None = None
    cursor: str | None = None
    correlation_id: str | None = Field(default=None, max_length=128)


class ReconciliationBatchItemRead(BaseModel):
    source_publication_id: UUID
    resulting_publication_id: UUID | None
    outcome: str
    changed: bool
    error_code: str | None = None


class ReconciliationBatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["preview", "run"]
    scanned: int
    processed: int
    changed: int
    verified: int
    missing: int
    checksum_conflict: int
    unchanged: int
    failed: int
    next_cursor: str | None
    items: tuple[ReconciliationBatchItemRead, ...]
