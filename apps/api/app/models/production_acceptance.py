from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

from app.db.base import Base

PRODUCTION_ACCEPTANCE_STATUSES = ("pending", "running", "passed", "failed", "blocked")
PRODUCTION_ACCEPTANCE_GATE_STATUSES = ("passed", "failed", "blocked", "not_evaluated")
PRODUCTION_ACCEPTANCE_DOMAINS = (
    "functional",
    "operational",
    "security",
    "recovery",
    "deployment",
    "capacity",
    "portal",
)


class ProductionAcceptanceRun(Base):
    __tablename__ = "production_acceptance_runs"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "contract_version",
            "input_hash",
            "idempotency_key",
            name="uq_runtime_production_acceptance_idempotency",
        ),
        CheckConstraint(
            f"status IN {PRODUCTION_ACCEPTANCE_STATUSES!r}",
            name="ck_runtime_production_acceptance_runs_status",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_production_acceptance_runs_scope"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_production_acceptance_runs_scope_org",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_production_acceptance_runs_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_runtime_production_acceptance_runs_result_hash",
        ),
        Index("ix_runtime_production_acceptance_runs_scope", "scope", "organization_id", "requested_at"),
        Index("ix_runtime_production_acceptance_runs_status", "status", "requested_at"),
        Index("ix_runtime_production_acceptance_runs_correlation", "correlation_id"),
        Index(
            "uq_runtime_production_acceptance_platform_idempotency",
            "scope",
            "contract_version",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_production_acceptance_org_idempotency",
            "scope",
            "organization_id",
            "contract_version",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", name="fk_runtime_prod_acceptance_runs_org")
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    production_ready: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductionAcceptanceGateResult(Base):
    __tablename__ = "production_acceptance_gate_results"
    __table_args__ = (
        UniqueConstraint("run_id", "gate_code", name="uq_runtime_production_acceptance_gate"),
        CheckConstraint(
            f"domain IN {PRODUCTION_ACCEPTANCE_DOMAINS!r}",
            name="ck_runtime_production_acceptance_gate_domain",
        ),
        CheckConstraint(
            f"status IN {PRODUCTION_ACCEPTANCE_GATE_STATUSES!r}",
            name="ck_runtime_production_acceptance_gate_status",
        ),
        Index("ix_runtime_production_acceptance_gate_run", "run_id", "domain"),
        Index("ix_runtime_production_acceptance_gate_status", "status", "mandatory"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.production_acceptance_runs.id",
            name="fk_runtime_prod_acceptance_gate_run",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    gate_code: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    blocker_code: Mapped[str | None] = mapped_column(String(128))
    warning_code: Mapped[str | None] = mapped_column(String(128))
    evidence_type: Mapped[str | None] = mapped_column(String(128))
    evidence_reference: Mapped[str | None] = mapped_column(String(255))
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    components_evaluated: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    evidence_origin: Mapped[str] = mapped_column(String(64), server_default="runtime", nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductionAcceptanceEvidence(Base):
    __tablename__ = "production_acceptance_evidence"
    __table_args__ = (
        UniqueConstraint("run_id", "evidence_hash", name="uq_runtime_production_acceptance_evidence_hash"),
        Index("ix_runtime_production_acceptance_evidence_run", "run_id", "evidence_type"),
        Index("ix_runtime_production_acceptance_evidence_gate", "gate_result_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.production_acceptance_runs.id",
            name="fk_runtime_prod_acceptance_evidence_run",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    gate_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.production_acceptance_gate_results.id",
            name="fk_runtime_prod_acceptance_evidence_gate",
            ondelete="SET NULL",
        ),
    )
    evidence_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str | None] = mapped_column(String(255))
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
