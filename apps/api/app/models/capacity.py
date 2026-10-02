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

CAPACITY_SCOPES = ("platform", "organization")
PROFILE_STATUSES = ("draft", "active", "inactive", "retired")
EXECUTION_STATUSES = ("pending", "running", "completed", "failed", "blocked", "cancelled")
EVALUATION_STATUSES = ("running", "passed", "failed", "blocked")
FINDING_STATUSES = ("open", "acknowledged", "resolved", "accepted")
RECOMMENDATION_STATUSES = ("open", "accepted", "implemented", "dismissed")
ACCEPTANCE_STATUSES = ("passed", "failed", "blocked", "not_evaluated")
CAPACITY_METRIC_CODES = (
    "concurrent_requests",
    "ingestion",
    "search",
    "assistant",
    "queue",
    "worker",
    "storage",
    "database",
)


def _scope_constraint(name: str) -> CheckConstraint:
    return CheckConstraint(
        "(scope = 'platform' AND organization_id IS NULL) OR "
        "(scope = 'organization' AND organization_id IS NOT NULL)",
        name=name,
    )


class CapacityProfile(Base):
    __tablename__ = "capacity_profiles"
    __table_args__ = (
        CheckConstraint(f"scope IN {CAPACITY_SCOPES!r}", name="ck_runtime_capacity_profiles_scope"),
        CheckConstraint(f"status IN {PROFILE_STATUSES!r}", name="ck_runtime_capacity_profiles_status"),
        CheckConstraint("evidence_max_age_hours > 0", name="ck_runtime_capacity_profiles_evidence_age"),
        _scope_constraint("ck_runtime_capacity_profiles_scope_org"),
        UniqueConstraint("scope", "organization_id", "profile_code", "version", name="uq_runtime_capacity_profile"),
        Index(
            "uq_runtime_capacity_profile_platform_identity",
            "profile_code",
            "version",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_capacity_profile_org_identity",
            "organization_id",
            "profile_code",
            "version",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        Index("ix_runtime_capacity_profiles_scope", "scope", "organization_id", "status", "updated_at"),
        Index(
            "uq_runtime_capacity_profile_active_platform",
            "scope",
            unique=True,
            postgresql_where=text("organization_id IS NULL AND status = 'active'"),
        ),
        Index(
            "uq_runtime_capacity_profile_active_org",
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
    status: Mapped[str] = mapped_column(String(32), server_default="draft", nullable=False)
    configured_capacity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_capacity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_max_age_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LoadTestExecution(Base):
    __tablename__ = "capacity_load_test_executions"
    __table_args__ = (
        CheckConstraint(f"scope IN {CAPACITY_SCOPES!r}", name="ck_runtime_capacity_load_scope"),
        CheckConstraint(f"status IN {EXECUTION_STATUSES!r}", name="ck_runtime_capacity_load_status"),
        CheckConstraint(
            "concurrent_requests > 0 AND duration_seconds > 0 AND requests_planned > 0",
            name="ck_runtime_capacity_load_positive_plan",
        ),
        CheckConstraint(
            "requests_completed >= 0 AND requests_failed >= 0",
            name="ck_runtime_capacity_load_nonnegative_results",
        ),
        _scope_constraint("ck_runtime_capacity_load_scope_org"),
        Index("ix_runtime_capacity_load_scope", "scope", "organization_id", "status", "requested_at"),
        Index(
            "uq_runtime_capacity_load_platform_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_capacity_load_org_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runtime.capacity_profiles.id"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    concurrent_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_planned: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_completed: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    requests_failed: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LoadTestResult(Base):
    __tablename__ = "capacity_load_test_results"
    __table_args__ = (
        CheckConstraint(f"metric_code IN {CAPACITY_METRIC_CODES!r}", name="ck_runtime_capacity_load_result_metric"),
        CheckConstraint(
            "observed_value >= 0 AND target_value >= 0 AND sample_count > 0",
            name="ck_runtime_capacity_load_result_values",
        ),
        UniqueConstraint("load_test_execution_id", "metric_code", name="uq_runtime_capacity_load_result_metric"),
        Index("ix_runtime_capacity_load_results_execution", "load_test_execution_id", "metric_code"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    load_test_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_load_test_executions.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(128), nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    target_value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    percentile_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CapacityEvaluation(Base):
    __tablename__ = "capacity_evaluations"
    __table_args__ = (
        CheckConstraint(f"scope IN {CAPACITY_SCOPES!r}", name="ck_runtime_capacity_evaluations_scope"),
        CheckConstraint(f"status IN {EVALUATION_STATUSES!r}", name="ck_runtime_capacity_evaluations_status"),
        _scope_constraint("ck_runtime_capacity_evaluations_scope_org"),
        Index("ix_runtime_capacity_evaluations_scope", "scope", "organization_id", "evaluated_at"),
        Index(
            "uq_runtime_capacity_evaluation_platform_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_capacity_evaluation_org_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runtime.capacity_profiles.id"))
    load_test_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_load_test_executions.id")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    configured_capacity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_capacity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_capacity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    utilization: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    bottlenecks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    recommendations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    next_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    evidence_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CapacityFinding(Base):
    __tablename__ = "capacity_findings"
    __table_args__ = (
        CheckConstraint(f"status IN {FINDING_STATUSES!r}", name="ck_runtime_capacity_findings_status"),
        UniqueConstraint("evaluation_id", "finding_code", name="uq_runtime_capacity_finding"),
        Index("ix_runtime_capacity_findings_evaluation", "evaluation_id", "severity", "status"),
        {"schema": "runtime"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    finding_code: Mapped[str] = mapped_column(String(128), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="open", nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CapacityRecommendation(Base):
    __tablename__ = "capacity_recommendations"
    __table_args__ = (
        CheckConstraint(
            f"status IN {RECOMMENDATION_STATUSES!r}", name="ck_runtime_capacity_recommendations_status"
        ),
        UniqueConstraint("evaluation_id", "recommendation_code", name="uq_runtime_capacity_recommendation"),
        Index("ix_runtime_capacity_recommendations_evaluation", "evaluation_id", "priority", "status"),
        {"schema": "runtime"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runtime.capacity_findings.id"))
    recommendation_code: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="open", nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CapacityEvidence(Base):
    __tablename__ = "capacity_evidence"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "evidence_code", "evidence_hash", name="uq_runtime_capacity_evidence"),
        Index("ix_runtime_capacity_evidence_evaluation", "evaluation_id", "observed_at"),
        {"schema": "runtime"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    load_test_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_load_test_executions.id")
    )
    evidence_code: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(255))
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HistoricalCapacityTrend(Base):
    __tablename__ = "capacity_trends"
    __table_args__ = (
        CheckConstraint(f"scope IN {CAPACITY_SCOPES!r}", name="ck_runtime_capacity_trends_scope"),
        _scope_constraint("ck_runtime_capacity_trends_scope_org"),
        CheckConstraint(f"metric_code IN {CAPACITY_METRIC_CODES!r}", name="ck_runtime_capacity_trends_metric"),
        CheckConstraint(
            "observed_value >= 0 AND configured_value >= 0 AND target_value >= 0 AND utilization_ratio >= 0",
            name="ck_runtime_capacity_trends_values",
        ),
        UniqueConstraint("evaluation_id", "metric_code", name="uq_runtime_capacity_trend_metric"),
        Index("ix_runtime_capacity_trends_scope_metric", "scope", "organization_id", "metric_code", "captured_at"),
        {"schema": "runtime"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    configured_value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    target_value: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    utilization_ratio: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapacityAcceptance(Base):
    __tablename__ = "capacity_acceptance"
    __table_args__ = (
        CheckConstraint(f"status IN {ACCEPTANCE_STATUSES!r}", name="ck_runtime_capacity_acceptance_status"),
        CheckConstraint(f"scope IN {CAPACITY_SCOPES!r}", name="ck_runtime_capacity_acceptance_scope_value"),
        _scope_constraint("ck_runtime_capacity_acceptance_scope_org"),
        CheckConstraint(
            "blocker_count >= 0 AND recommendation_count >= 0 AND "
            "(evidence_age_seconds IS NULL OR evidence_age_seconds >= 0)",
            name="ck_runtime_capacity_acceptance_counts",
        ),
        UniqueConstraint("evaluation_id", name="uq_runtime_capacity_acceptance_evaluation"),
        Index("ix_runtime_capacity_acceptance_scope", "scope", "organization_id", "accepted_at"),
        {"schema": "runtime"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runtime.capacity_profiles.id"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
