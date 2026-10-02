from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("artifact_id", "publication_id", name="uq_knowledge_documents_artifact_publication"),
        Index("ix_knowledge_documents_artifact_id", "artifact_id"),
        Index("ix_knowledge_documents_publication_id", "publication_id"),
        Index("ix_knowledge_documents_status", "status"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_record_id: Mapped[str | None] = mapped_column(String(128))
    document_version_id: Mapped[str | None] = mapped_column(String(128))
    publication_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="indexed", nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    content_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        server_default=sa_text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeChunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("knowledge_document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
        UniqueConstraint("published_chunk_id", name="uq_knowledge_chunks_published_chunk_id"),
        Index("ix_knowledge_chunks_document_id", "knowledge_document_id"),
        Index("ix_knowledge_chunks_content_hash", "content_hash"),
        Index("ix_knowledge_chunks_semantic_hash", "semantic_hash"),
        Index("ix_knowledge_chunks_status", "status"),
        Index("ix_knowledge_chunks_search_vector", "search_vector", postgresql_using="gin"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    published_chunk_id: Mapped[str] = mapped_column(String(255), nullable=False)
    publication_id: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_hash: Mapped[str | None] = mapped_column(String(128))
    content_type: Mapped[str | None] = mapped_column(String(128))
    chunk_scope: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), server_default="indexed", nullable=False)
    search_vector: Mapped[Any | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        server_default=sa_text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmbeddingRecord(Base):
    __tablename__ = "embedding_records"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_name", "model_version", name="uq_knowledge_embedding_records_chunk_model"),
        CheckConstraint("embedding_dimensions >= 0", name="ck_knowledge_embedding_records_dimensions"),
        CheckConstraint(
            "embedding_status IN ('pending','completed','failed')", name="ck_knowledge_embedding_records_status"
        ),
        Index("ix_knowledge_embedding_records_chunk_id", "chunk_id"),
        Index("ix_knowledge_embedding_records_status", "embedding_status"),
        Index("ix_knowledge_embedding_records_model", "model_name", "model_version"),
        {"schema": "knowledge"},
    )

    embedding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    embedding_hash: Mapped[str | None] = mapped_column(String(128))
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VectorIndexRecord(Base):
    __tablename__ = "vector_index_records"
    __table_args__ = (
        UniqueConstraint(
            "embedding_id",
            "index_name",
            "index_provider",
            "index_version",
            name="uq_knowledge_vector_index_records_embedding_index",
        ),
        CheckConstraint(
            "index_status IN ('planned','prepared','indexed','failed','disabled')",
            name="ck_knowledge_vector_index_records_status",
        ),
        CheckConstraint("vector_dimensions >= 0", name="ck_knowledge_vector_index_records_dimensions"),
        Index("ix_knowledge_vector_index_records_embedding_id", "embedding_id"),
        Index("ix_knowledge_vector_index_records_chunk_id", "knowledge_chunk_id"),
        Index("ix_knowledge_vector_index_records_status", "index_status"),
        Index("ix_knowledge_vector_index_records_provider", "index_provider"),
        {"schema": "knowledge"},
    )

    vector_index_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    embedding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.embedding_records.embedding_id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    index_name: Mapped[str] = mapped_column(String(255), nullable=False)
    index_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    index_provider_type: Mapped[str] = mapped_column(String(128), nullable=False)
    index_status: Mapped[str] = mapped_column(String(32), server_default="planned", nullable=False)
    index_version: Mapped[str] = mapped_column(String(128), nullable=False)
    vector_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_hash: Mapped[str | None] = mapped_column(String(128))
    external_index_id: Mapped[str | None] = mapped_column(String(255))
    external_point_id: Mapped[str | None] = mapped_column(String(255))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeMetadata(Base):
    __tablename__ = "metadata"
    __table_args__ = (
        UniqueConstraint("knowledge_document_id", "metadata_key", name="uq_knowledge_metadata_document_key"),
        Index("ix_knowledge_metadata_document_id", "knowledge_document_id"),
        Index("ix_knowledge_metadata_key", "metadata_key"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    metadata_key: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_value: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=sa_text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeLifecycleRun(Base):
    __tablename__ = "lifecycle_runs"
    __table_args__ = (
        Index("ix_knowledge_lifecycle_runs_operation", "operation"),
        Index("ix_knowledge_lifecycle_runs_status", "status"),
        Index("ix_knowledge_lifecycle_runs_artifact_id", "artifact_id"),
        Index("ix_knowledge_lifecycle_runs_publication_id", "publication_id"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lifecycle_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(128))
    publication_id: Mapped[str | None] = mapped_column(String(255))
    document_id: Mapped[str | None] = mapped_column(String(128))
    decision: Mapped[str | None] = mapped_column(String(32))
    documents_scanned: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    documents_updated: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    documents_invalidated: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    documents_deleted: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    chunks_scanned: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    chunks_updated: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    chunks_deleted: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    duplicates_removed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    orphan_chunks_removed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    stale_documents_removed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    obsolete_publications_removed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result", JSONB, server_default=sa_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeIndexHealthSnapshot(Base):
    __tablename__ = "index_health_snapshots"
    __table_args__ = (
        Index("ix_knowledge_index_health_snapshots_created_at", "created_at"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    indexed_documents: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    indexed_chunks: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    stale_documents: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    orphan_chunks: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    duplicate_chunks: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    pending_updates: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    pending_reindex: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_incremental: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_full_reindex: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rebuild_required: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    statistics_json: Mapped[dict[str, Any]] = mapped_column(
        "statistics", JSONB, server_default=sa_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
