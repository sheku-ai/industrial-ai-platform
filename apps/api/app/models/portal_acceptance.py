from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PORTAL_VALIDATION_TYPES = (
    "principal_routes",
    "portal_build",
    "portal_contract",
    "negative_states",
    "permission_states",
    "cross_organization_states",
)
PORTAL_VALIDATION_STATUSES = ("passed", "failed", "blocked", "not_evaluated")


class PortalAcceptanceEvidence(Base):
    __tablename__ = "portal_acceptance_evidence"
    __table_args__ = (
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_portal_evidence_scope"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_portal_evidence_scope_org",
        ),
        CheckConstraint(
            f"validation_type IN {PORTAL_VALIDATION_TYPES!r}",
            name="ck_runtime_portal_evidence_type",
        ),
        CheckConstraint(
            f"status IN {PORTAL_VALIDATION_STATUSES!r}",
            name="ck_runtime_portal_evidence_status",
        ),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_portal_evidence_hash"),
        CheckConstraint(
            "status <> 'passed' OR evidence_payload <> '{}'::jsonb",
            name="ck_runtime_portal_evidence_passed_payload",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_runtime_portal_evidence_completion",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at",
            name="ck_runtime_portal_evidence_expiry",
        ),
        Index("ix_runtime_portal_evidence_scope", "scope", "organization_id", "observed_at"),
        Index("ix_runtime_portal_evidence_run", "validation_run_code", "validation_type"),
        Index(
            "uq_runtime_portal_evidence_platform_identity",
            "validation_run_code",
            "validation_type",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_portal_evidence_org_identity",
            "organization_id",
            "validation_run_code",
            "validation_type",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id")
    )
    validation_run_code: Mapped[str] = mapped_column(String(128), nullable=False)
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(512))
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
