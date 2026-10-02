from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from app.db.base import Base


class RuntimeArtifactPublication(Base):
    __tablename__ = "artifact_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id"],
            ["runtime.execution_artifacts.id"],
            name="fk_runtime_artifact_publications_artifact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "execution_id", "attempt_id"],
            [
                "runtime.execution_attempts.organization_id",
                "runtime.execution_attempts.execution_id",
                "runtime.execution_attempts.id",
            ],
            name="fk_runtime_artifact_publications_attempt",
        ),
        UniqueConstraint("artifact_id", "publication_number", name="uq_runtime_artifact_publications_number"),
        CheckConstraint("publication_number > 0", name=conv("ck_runtime_artifact_publications_number")),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name=conv("ck_runtime_artifact_publications_size")),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_runtime_artifact_publications_checksum"),
        ),
        CheckConstraint(
            "status IN ('reserved','publishing','published','verified','missing','checksum_conflict',"
            "'reconciliation_required','failed','retained','deleted')",
            name=conv("ck_runtime_artifact_publications_status"),
        ),
        CheckConstraint(
            "verified_at IS NULL OR published_at IS NOT NULL",
            name=conv("ck_runtime_artifact_publications_verified_after_publish"),
        ),
        Index("ix_runtime_artifact_publications_status", "organization_id", "execution_id", "status"),
        Index("ix_runtime_artifact_publications_artifact", "organization_id", "artifact_id", "created_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    publication_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
