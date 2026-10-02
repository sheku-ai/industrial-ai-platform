from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SecurityPolicyRuntime(Base):
    __tablename__ = "security_acceptance_policies"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "policy_code",
            name="uq_runtime_security_acceptance_policy_code",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_policy_scope"),
        CheckConstraint("status IN ('draft','active','inactive','retired')", name="ck_runtime_security_policy_status"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_security_policy_scope_org",
        ),
        Index("ix_runtime_security_policy_scope", "scope", "organization_id", "status"),
        Index(
            "uq_runtime_security_policy_platform_active",
            "scope",
            unique=True,
            postgresql_where=text("organization_id IS NULL AND status = 'active'"),
        ),
        Index(
            "uq_runtime_security_policy_org_active",
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
    policy_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="draft", nullable=False)
    authentication_required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    authorization_required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    debug_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    cors_profile: Mapped[str] = mapped_column(String(64), server_default="restricted", nullable=False)
    provider_execution_policy: Mapped[str] = mapped_column(String(64), server_default="explicit", nullable=False)
    placeholder_detection_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    required_secrets: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    required_configuration: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    audit_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    organization_isolation_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    configuration_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SecurityFinding(Base):
    __tablename__ = "security_acceptance_findings"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "rule",
            "source_runtime",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_security_finding_identity",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_finding_scope"),
        CheckConstraint(
            "severity IN ('info','warning','high','critical')", name="ck_runtime_security_finding_severity"
        ),
        CheckConstraint(
            "status IN ('open','acknowledged','resolved','suppressed')",
            name="ck_runtime_security_finding_status",
        ),
        Index("ix_runtime_security_finding_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_security_finding_severity", "severity", "status"),
        Index("ix_runtime_security_finding_rule", "rule", "category"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="open", nullable=False)
    rule: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    remediation: Mapped[str | None] = mapped_column(Text)
    source_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str | None] = mapped_column(String(255))
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SecurityEvidence(Base):
    __tablename__ = "security_acceptance_evidence"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "source_runtime",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_security_evidence_identity",
        ),
        CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_security_evidence_scope"),
        CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')",
            name="ck_runtime_security_evidence_status",
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_security_evidence_expiry"),
        Index("ix_runtime_security_evidence_scope", "scope", "organization_id", "status"),
        Index("ix_runtime_security_evidence_type", "evidence_type", "observed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
