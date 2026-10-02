from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestionSegmentPlan(Base):
    __tablename__ = "segment_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_documents_segment_plans_execution",
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "execution_id", name="uq_documents_segment_plans_execution"),
        CheckConstraint(
            "status IN ('planned','processing','completed','failed','cancelled')",
            name="ck_documents_segment_plans_status",
        ),
        CheckConstraint("segment_count > 0", name="ck_documents_segment_plans_segment_count"),
        Index("ix_documents_segment_plans_status", "organization_id", "status", "created_at"),
        {"schema": "documents"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_class: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="planned")
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IngestionSegment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id"],
            ["documents.segment_plans.id"],
            name="fk_documents_segments_plan",
            ondelete="CASCADE",
        ),
        UniqueConstraint("plan_id", "ordinal", name="uq_documents_segments_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_documents_segments_ordinal"),
        CheckConstraint("range_start >= 0", name="ck_documents_segments_range_start"),
        CheckConstraint("range_end_exclusive > range_start", name="ck_documents_segments_range"),
        CheckConstraint(
            "status IN ('pending','processing','completed','failed','cancelled')", name="ck_documents_segments_status"
        ),
        Index("ix_documents_segments_status", "plan_id", "status", "ordinal"),
        {"schema": "documents"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_key: Mapped[str] = mapped_column(String(128), nullable=False)
    range_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    range_end_exclusive: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
