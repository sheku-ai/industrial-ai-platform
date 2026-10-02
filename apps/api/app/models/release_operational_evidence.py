from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseOperationalEvidence(Base):
    __tablename__ = "release_operational_evidence"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "execution_key",
            name="uq_runtime_release_operational_evidence_execution",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_release_operational_scope"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_release_operational_scope_org",
        ),
        CheckConstraint(
            "evidence_type IN ('configuration_preflight','upgrade_readiness','rollback_eligibility',"
            "'rc_operational_refresh')",
            name="ck_runtime_release_operational_type",
        ),
        CheckConstraint(
            "status IN ('passed','failed','blocked','expired','not_evaluated','requires_restore',"
            "'eligible_application_only','incompatible')",
            name="ck_runtime_release_operational_status",
        ),
        CheckConstraint(
            "edition IS NULL OR edition IN ('community','enterprise')",
            name="ck_runtime_release_operational_edition",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_release_operational_input_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_operational_evidence_hash"),
        Index(
            "ix_runtime_release_operational_latest",
            "scope",
            "organization_id",
            "evidence_type",
            "evaluated_at",
        ),
        Index("ix_runtime_release_operational_correlation", "correlation_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="CASCADE")
    )
    backup_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.backup_executions.id", ondelete="RESTRICT")
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    release_version: Mapped[str] = mapped_column(String(64), nullable=False)
    alembic_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_key: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
