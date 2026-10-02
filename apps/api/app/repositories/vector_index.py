from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_index import EmbeddingRecord, KnowledgeChunk, VectorIndexRecord


class VectorIndexRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_embedding(self, embedding_id: uuid.UUID) -> EmbeddingRecord | None:
        return self.session.get(EmbeddingRecord, embedding_id)

    def get_chunk(self, chunk_id: uuid.UUID) -> KnowledgeChunk | None:
        return self.session.get(KnowledgeChunk, chunk_id)

    def create_vector_index_record(
        self,
        *,
        embedding_id: uuid.UUID,
        knowledge_chunk_id: uuid.UUID,
        knowledge_document_id: uuid.UUID,
        index_name: str,
        index_provider: str,
        index_provider_type: str,
        index_version: str,
        vector_dimensions: int,
        vector_hash: str | None = None,
        external_index_id: str | None = None,
        external_point_id: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> tuple[VectorIndexRecord, bool]:
        statement = select(VectorIndexRecord).where(
            VectorIndexRecord.embedding_id == embedding_id,
            VectorIndexRecord.index_name == index_name,
            VectorIndexRecord.index_provider == index_provider,
            VectorIndexRecord.index_version == index_version,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            existing.knowledge_chunk_id = knowledge_chunk_id
            existing.knowledge_document_id = knowledge_document_id
            existing.index_provider_type = index_provider_type
            existing.vector_dimensions = int(vector_dimensions)
            existing.vector_hash = vector_hash or existing.vector_hash
            existing.external_index_id = external_index_id or existing.external_index_id
            existing.external_point_id = external_point_id or existing.external_point_id
            existing.runtime_metadata = {**(existing.runtime_metadata or {}), **dict(runtime_metadata or {})}
            self.session.add(existing)
            self.session.flush()
            return existing, False
        record = VectorIndexRecord(
            embedding_id=embedding_id,
            knowledge_chunk_id=knowledge_chunk_id,
            knowledge_document_id=knowledge_document_id,
            index_name=index_name,
            index_provider=index_provider,
            index_provider_type=index_provider_type,
            index_status="planned",
            index_version=index_version,
            vector_dimensions=int(vector_dimensions),
            vector_hash=vector_hash,
            external_index_id=external_index_id,
            external_point_id=external_point_id,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def get_vector_index_record(self, vector_index_id: uuid.UUID) -> VectorIndexRecord | None:
        return self.session.get(VectorIndexRecord, vector_index_id)

    def list_vector_index_records(
        self,
        *,
        embedding_id: uuid.UUID | None = None,
        knowledge_chunk_id: uuid.UUID | None = None,
        index_status: str | None = None,
        limit: int = 100,
    ) -> list[VectorIndexRecord]:
        statement = select(VectorIndexRecord)
        if embedding_id is not None:
            statement = statement.where(VectorIndexRecord.embedding_id == embedding_id)
        if knowledge_chunk_id is not None:
            statement = statement.where(VectorIndexRecord.knowledge_chunk_id == knowledge_chunk_id)
        if index_status:
            statement = statement.where(VectorIndexRecord.index_status == index_status)
        statement = statement.order_by(
            VectorIndexRecord.created_at.asc(), VectorIndexRecord.vector_index_id.asc()
        ).limit(max(1, min(int(limit), 500)))
        return list(self.session.scalars(statement).all())

    def list_pending_vector_index_records(self, *, limit: int = 100) -> list[VectorIndexRecord]:
        statement = select(VectorIndexRecord).where(VectorIndexRecord.index_status.in_(("planned", "prepared")))
        statement = statement.order_by(
            VectorIndexRecord.created_at.asc(), VectorIndexRecord.vector_index_id.asc()
        ).limit(max(1, min(int(limit), 500)))
        return list(self.session.scalars(statement).all())

    def mark_vector_index_prepared(
        self,
        vector_index_id: uuid.UUID,
        *,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> VectorIndexRecord | None:
        record = self.get_vector_index_record(vector_index_id)
        if record is None:
            return None
        record.index_status = "prepared"
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_vector_index_indexed(
        self,
        vector_index_id: uuid.UUID,
        *,
        external_index_id: str | None = None,
        external_point_id: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> VectorIndexRecord | None:
        record = self.get_vector_index_record(vector_index_id)
        if record is None:
            return None
        record.index_status = "indexed"
        record.indexed_at = datetime.now(UTC)
        record.external_index_id = external_index_id or record.external_index_id
        record.external_point_id = external_point_id or record.external_point_id
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_vector_index_failed(
        self,
        vector_index_id: uuid.UUID,
        *,
        failure_reason: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> VectorIndexRecord | None:
        record = self.get_vector_index_record(vector_index_id)
        if record is None:
            return None
        record.index_status = "failed"
        record.failed_at = datetime.now(UTC)
        record.failure_reason = failure_reason
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def disable_vector_index_record(
        self,
        vector_index_id: uuid.UUID,
        *,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> VectorIndexRecord | None:
        record = self.get_vector_index_record(vector_index_id)
        if record is None:
            return None
        record.index_status = "disabled"
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record
