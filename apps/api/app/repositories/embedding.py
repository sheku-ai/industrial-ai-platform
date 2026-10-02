from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_index import EmbeddingRecord


class EmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_embedding_record(
        self,
        *,
        chunk_id: uuid.UUID,
        model_name: str,
        model_version: str,
        embedding_dimensions: int,
        embedding_hash: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> tuple[EmbeddingRecord, bool]:
        statement = select(EmbeddingRecord).where(
            EmbeddingRecord.chunk_id == chunk_id,
            EmbeddingRecord.model_name == model_name,
            EmbeddingRecord.model_version == model_version,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            existing.embedding_dimensions = int(embedding_dimensions)
            existing.embedding_hash = embedding_hash or existing.embedding_hash
            existing.runtime_metadata = {**(existing.runtime_metadata or {}), **dict(runtime_metadata or {})}
            self.session.add(existing)
            self.session.flush()
            return existing, False
        record = EmbeddingRecord(
            chunk_id=chunk_id,
            model_name=model_name,
            model_version=model_version,
            embedding_dimensions=int(embedding_dimensions),
            embedding_status="pending",
            embedding_hash=embedding_hash,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def get_embedding(self, embedding_id: uuid.UUID) -> EmbeddingRecord | None:
        return self.session.get(EmbeddingRecord, embedding_id)

    def list_embeddings(
        self,
        *,
        chunk_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[EmbeddingRecord]:
        statement = select(EmbeddingRecord)
        if chunk_id is not None:
            statement = statement.where(EmbeddingRecord.chunk_id == chunk_id)
        if status:
            statement = statement.where(EmbeddingRecord.embedding_status == status)
        statement = statement.order_by(EmbeddingRecord.created_at.asc(), EmbeddingRecord.embedding_id.asc()).limit(
            max(1, min(int(limit), 500))
        )
        return list(self.session.scalars(statement).all())

    def list_pending_embeddings(self, *, limit: int = 100) -> list[EmbeddingRecord]:
        return self.list_embeddings(status="pending", limit=limit)

    def mark_embedding_completed(
        self,
        embedding_id: uuid.UUID,
        *,
        embedding_hash: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> EmbeddingRecord | None:
        record = self.get_embedding(embedding_id)
        if record is None:
            return None
        record.embedding_status = "completed"
        record.embedding_hash = embedding_hash
        record.embedding_created_at = datetime.now(UTC)
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_embedding_failed(
        self,
        embedding_id: uuid.UUID,
        *,
        error_code: str,
        error_message: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> EmbeddingRecord | None:
        record = self.get_embedding(embedding_id)
        if record is None:
            return None
        record.embedding_status = "failed"
        record.runtime_metadata = {
            **(record.runtime_metadata or {}),
            **dict(runtime_metadata or {}),
            "error_code": error_code,
            "error_message": error_message,
        }
        self.session.add(record)
        self.session.flush()
        return record
