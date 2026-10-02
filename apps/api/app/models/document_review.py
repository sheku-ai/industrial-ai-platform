import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentReviewCase(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_review_cases"
    __table_args__ = (
        Index("ix_document_review_cases_org_status", "organization_id", "status"),
        Index("ix_document_review_cases_document_version", "document_version_id"),
        Index("ix_document_review_cases_expires_at", "expires_at"),
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
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.ingestion_jobs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending_human_review")
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_format: Mapped[str] = mapped_column(String(128), nullable=False)
    detected_by: Mapped[str] = mapped_column(String(128), nullable=False)
    encryption_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allowed_actions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    secret_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    secret_expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    secret_single_use: Mapped[bool] = mapped_column(default=True, nullable=False)
    expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentReviewEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_review_events"
    __table_args__ = (
        Index("ix_document_review_events_review_created", "review_case_id", "created_at"),
        Index("ix_document_review_events_organization", "organization_id"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    review_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_review_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
