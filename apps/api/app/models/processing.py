import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProcessingRevision(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "processing_revisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "runtime_execution_id",
            "runtime_attempt_id",
            name="uq_processing_revisions_runtime_attempt",
        ),
        Index("ix_processing_revisions_document_version_id", "document_version_id"),
        Index("ix_processing_revisions_runtime_execution_id", "runtime_execution_id"),
        Index("ix_processing_revisions_status", "status"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    document_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_versions.id"), nullable=False
    )
    runtime_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.executions.id"), nullable=False
    )
    runtime_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.execution_attempts.id"), nullable=False
    )
    pipeline_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.ingestion_pipeline_profiles.id"), nullable=True
    )
    pipeline_profile_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source_checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_unit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manifest_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.execution_artifacts.id"), nullable=True
    )
