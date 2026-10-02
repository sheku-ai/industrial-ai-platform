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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

OBSERVABILITY_SCOPES = ("platform", "organization")
PROFILE_STATUSES = ("draft", "active", "inactive", "retired")
RESOURCE_STATUSES = ("active", "inactive", "degraded", "failed", "unknown")
SIGNAL_STATUSES = ("healthy", "degraded", "failed", "unknown")
EVALUATION_STATUSES = ("healthy", "degraded", "failed", "blocked", "not_evaluated")
FINDING_STATUSES = ("open", "acknowledged", "resolved", "accepted")


def _scope_constraint(name: str) -> CheckConstraint:
    return CheckConstraint(
        "(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)",
        name=name,
    )


class ObservabilityProfile(Base):
    __tablename__ = "observability_profiles"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_profile_scope"),
        CheckConstraint(f"status IN {PROFILE_STATUSES!r}", name="ck_runtime_observability_profile_status"),
        CheckConstraint(
            "evidence_max_age_seconds > 0 AND heartbeat_max_age_seconds > 0",
            name="ck_runtime_observability_profile_freshness",
        ),
        CheckConstraint(
            "minimum_availability_percentage BETWEEN 0 AND 100 "
            "AND minimum_signal_coverage_percentage BETWEEN 0 AND 100",
            name="ck_runtime_observability_profile_thresholds",
        ),
        _scope_constraint("ck_runtime_observability_profile_scope_org"),
        Index(
            "uq_runtime_observability_profile_platform",
            "profile_code",
            "version",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_observability_profile_org",
            "organization_id",
            "profile_code",
            "version",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        Index(
            "uq_runtime_observability_profile_active_platform",
            "scope",
            unique=True,
            postgresql_where=text("organization_id IS NULL AND status = 'active'"),
        ),
        Index(
            "uq_runtime_observability_profile_active_org",
            "scope",
            "organization_id",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL AND status = 'active'"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    evidence_max_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    heartbeat_max_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_availability_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    minimum_signal_coverage_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[str | None] = mapped_column(String(255))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthDomain(Base):
    __tablename__ = "observability_health_domains"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_domain_scope"),
        CheckConstraint(f"status IN {RESOURCE_STATUSES!r}", name="ck_runtime_observability_domain_status"),
        _scope_constraint("ck_runtime_observability_domain_scope_org"),
        UniqueConstraint("profile_id", "domain_code", "version", name="uq_runtime_observability_domain"),
        Index("ix_runtime_observability_domain_scope", "scope", "organization_id", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_profiles.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    required_component_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ObservedComponent(Base):
    __tablename__ = "observability_components"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_component_scope"),
        CheckConstraint(f"status IN {RESOURCE_STATUSES!r}", name="ck_runtime_observability_component_status"),
        _scope_constraint("ck_runtime_observability_component_scope_org"),
        UniqueConstraint("health_domain_id", "component_code", "version", name="uq_runtime_observability_component"),
        Index("ix_runtime_observability_component_scope", "scope", "organization_id", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    health_domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_health_domains.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    component_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    component_type: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    required_signal_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    component_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ObservedDependency(Base):
    __tablename__ = "observability_dependencies"
    __table_args__ = (
        CheckConstraint(f"status IN {RESOURCE_STATUSES!r}", name="ck_runtime_observability_dependency_status"),
        UniqueConstraint("component_id", "dependency_code", "version", name="uq_runtime_observability_dependency"),
        Index("ix_runtime_observability_dependency_component", "component_id", "status", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False
    )
    dependency_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dependency_type: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ObservedSignal(Base):
    __tablename__ = "observability_signals"
    __table_args__ = (
        CheckConstraint(f"status IN {SIGNAL_STATUSES!r}", name="ck_runtime_observability_signal_status"),
        UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_signal_idempotency"),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_signal_hash"),
        Index("ix_runtime_observability_signal_component", "component_id", "signal_code", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False
    )
    signal_code: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ObservabilityHeartbeat(Base):
    __tablename__ = "observability_heartbeats"
    __table_args__ = (
        CheckConstraint("status IN ('healthy','degraded','failed')", name="ck_runtime_observability_heartbeat_status"),
        UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_heartbeat_idempotency"),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_heartbeat_hash"),
        Index("ix_runtime_observability_heartbeat_component", "component_id", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AvailabilityWindow(Base):
    __tablename__ = "observability_availability_windows"
    __table_args__ = (
        UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_availability_idempotency"),
        CheckConstraint("window_end > window_start", name="ck_runtime_observability_availability_window"),
        CheckConstraint(
            "availability_percentage BETWEEN 0 AND 100", name="ck_runtime_observability_availability_percentage"
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_availability_hash"),
        Index("ix_runtime_observability_availability_component", "component_id", "window_end"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    unavailable_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    availability_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthEvaluation(Base):
    __tablename__ = "observability_health_evaluations"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_evaluation_scope"),
        CheckConstraint(
            f"overall_health IN {EVALUATION_STATUSES!r}", name="ck_runtime_observability_evaluation_health"
        ),
        _scope_constraint("ck_runtime_observability_evaluation_scope_org"),
        Index(
            "uq_runtime_observability_evaluation_platform_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_observability_evaluation_org_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        Index("ix_runtime_observability_evaluation_scope", "scope", "organization_id", "evaluated_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_profiles.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_health: Mapped[str] = mapped_column(String(32), nullable=False)
    availability_status: Mapped[str] = mapped_column(String(32), nullable=False)
    heartbeat_status: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    dependency_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    component_status: Mapped[str] = mapped_column(String(32), nullable=False)
    acceptance_status: Mapped[str] = mapped_column(String(32), nullable=False)
    availability_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    signal_coverage_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    recommendations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    next_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthFinding(Base):
    __tablename__ = "observability_health_findings"
    __table_args__ = (
        CheckConstraint(f"status IN {FINDING_STATUSES!r}", name="ck_runtime_observability_finding_status"),
        UniqueConstraint("evaluation_id", "finding_code", name="uq_runtime_observability_finding"),
        Index("ix_runtime_observability_finding_evaluation", "evaluation_id", "severity", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_components.id")
    )
    dependency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.observability_dependencies.id")
    )
    finding_code: Mapped[str] = mapped_column(String(160), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="open")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthEvidence(Base):
    __tablename__ = "observability_health_evidence"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "evidence_hash", name="uq_runtime_observability_health_evidence"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_observability_evidence_hash"),
        Index("ix_runtime_observability_evidence_evaluation", "evaluation_id", "evaluation_timestamp"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    dependency_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    heartbeat_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    signal_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    finding_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthAcceptance(Base):
    __tablename__ = "observability_health_acceptance"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_acceptance_scope"),
        _scope_constraint("ck_runtime_observability_acceptance_scope_org"),
        UniqueConstraint("evaluation_id", name="uq_runtime_observability_acceptance_evaluation"),
        Index("ix_runtime_observability_acceptance_scope", "scope", "organization_id", "accepted_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    accepted_by: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthHistory(Base):
    __tablename__ = "observability_health_history"
    __table_args__ = (
        CheckConstraint(f"scope IN {OBSERVABILITY_SCOPES!r}", name="ck_runtime_observability_history_scope"),
        _scope_constraint("ck_runtime_observability_history_scope_org"),
        UniqueConstraint("evaluation_id", name="uq_runtime_observability_history_evaluation"),
        Index("ix_runtime_observability_history_scope", "scope", "organization_id", "captured_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_health: Mapped[str] = mapped_column(String(32), nullable=False)
    availability_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    signal_coverage_percentage: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    component_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dependency_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    finding_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
