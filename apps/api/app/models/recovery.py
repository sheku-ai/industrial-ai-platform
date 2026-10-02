from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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

RECOVERY_SCOPES = ("platform", "organization")
RECOVERY_POLICY_STATUSES = ("draft", "active", "inactive", "retired")
BACKUP_EXECUTION_STATUSES = ("pending", "running", "completed", "failed", "cancelled", "blocked")
BACKUP_TYPES = ("full", "incremental", "differential", "snapshot", "external")
ARTIFACT_RESOURCE_TYPES = (
    "postgresql",
    "platform_postgresql",
    "identity_postgresql",
    "object_storage",
    "application_configuration",
    "migration_manifest",
    "release_manifest",
    "other",
)
ARTIFACT_VERIFICATION_STATUSES = ("pending", "verified", "failed", "not_supported")
RESTORE_EXECUTION_STATUSES = ("requested", "approved", "running", "completed", "failed", "cancelled", "blocked")
RESTORE_TARGET_TYPES = (
    "isolated_validation_environment",
    "replacement_environment",
    "existing_environment",
    "external_target",
)
RESTORE_VERIFICATION_STATUSES = ("pending", "running", "passed", "failed", "blocked")
RECOVERY_EVIDENCE_STATUSES = ("passed", "failed", "blocked", "not_evaluated")


class RecoveryPolicy(Base):
    __tablename__ = "recovery_policies"
    __table_args__ = (
        CheckConstraint(f"scope IN {RECOVERY_SCOPES!r}", name="ck_runtime_recovery_policies_scope"),
        CheckConstraint(f"status IN {RECOVERY_POLICY_STATUSES!r}", name="ck_runtime_recovery_policies_status"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_recovery_policies_scope_org",
        ),
        CheckConstraint(
            "retention_days IS NULL OR retention_days > 0", name="ck_runtime_recovery_policies_retention_days"
        ),
        CheckConstraint(
            "retention_count IS NULL OR retention_count > 0", name="ck_runtime_recovery_policies_retention_count"
        ),
        CheckConstraint("rpo_minutes IS NULL OR rpo_minutes > 0", name="ck_runtime_recovery_policies_rpo"),
        CheckConstraint("rto_minutes IS NULL OR rto_minutes > 0", name="ck_runtime_recovery_policies_rto"),
        CheckConstraint(
            "evidence_max_age_hours IS NULL OR evidence_max_age_hours > 0",
            name="ck_runtime_recovery_policies_evidence_age",
        ),
        Index("ix_runtime_recovery_policies_scope", "scope", "organization_id", "status"),
        Index(
            "uq_runtime_recovery_policy_active_platform",
            "scope",
            unique=True,
            postgresql_where=text("organization_id IS NULL AND status = 'active'"),
        ),
        Index(
            "uq_runtime_recovery_policy_active_org",
            "scope",
            "organization_id",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL AND status = 'active'"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", name="fk_runtime_recovery_policies_org")
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="draft", nullable=False)
    database_backup_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    object_storage_backup_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    configuration_backup_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    backup_frequency: Mapped[str | None] = mapped_column(String(128))
    retention_days: Mapped[int | None] = mapped_column(Integer)
    retention_count: Mapped[int | None] = mapped_column(Integer)
    rpo_minutes: Mapped[int | None] = mapped_column(Integer)
    rto_minutes: Mapped[int | None] = mapped_column(Integer)
    verification_required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    restore_test_frequency: Mapped[str | None] = mapped_column(String(128))
    evidence_max_age_hours: Mapped[int | None] = mapped_column(Integer)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    configuration_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupExecution(Base):
    __tablename__ = "backup_executions"
    __table_args__ = (
        CheckConstraint(f"scope IN {RECOVERY_SCOPES!r}", name="ck_runtime_backup_executions_scope"),
        CheckConstraint(f"status IN {BACKUP_EXECUTION_STATUSES!r}", name="ck_runtime_backup_executions_status"),
        CheckConstraint(f"backup_type IN {BACKUP_TYPES!r}", name="ck_runtime_backup_executions_type"),
        CheckConstraint("artifact_count >= 0", name="ck_runtime_backup_executions_artifact_count"),
        CheckConstraint("total_size_bytes IS NULL OR total_size_bytes >= 0", name="ck_runtime_backup_executions_size"),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_backup_executions_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_backup_executions_result_hash"
        ),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_backup_executions_scope_org",
        ),
        Index("ix_runtime_backup_executions_scope", "scope", "organization_id", "status", "requested_at"),
        Index("ix_runtime_backup_executions_policy", "policy_id", "status", "completed_at"),
        Index("ix_runtime_backup_executions_correlation", "correlation_id"),
        Index(
            "uq_runtime_backup_execution_platform_idempotency",
            "scope",
            "provider_type",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_backup_execution_org_idempotency",
            "scope",
            "organization_id",
            "provider_type",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.recovery_policies.id", name="fk_runtime_backup_execution_policy")
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_execution_id: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    backup_type: Mapped[str] = mapped_column(String(32), nullable=False)
    database_included: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    object_storage_included: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    configuration_included: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    consistent_snapshot: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    total_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    manifest_hash: Mapped[str | None] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BackupArtifactEvidence(Base):
    __tablename__ = "backup_artifact_evidence"
    __table_args__ = (
        CheckConstraint(
            f"resource_type IN {ARTIFACT_RESOURCE_TYPES!r}",
            name="ck_runtime_backup_artifact_resource_type",
        ),
        CheckConstraint(
            f"verification_status IN {ARTIFACT_VERIFICATION_STATUSES!r}",
            name="ck_runtime_backup_artifact_verification_status",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_backup_artifact_size"),
        Index("ix_runtime_backup_artifact_execution", "backup_execution_id", "resource_type"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backup_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.backup_executions.id", name="fk_runtime_backup_artifact_execution", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    storage_location_masked: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str | None] = mapped_column(String(255))
    encryption_status: Mapped[str | None] = mapped_column(String(64))
    compression_status: Mapped[str | None] = mapped_column(String(64))
    created_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RestoreExecution(Base):
    __tablename__ = "restore_executions"
    __table_args__ = (
        CheckConstraint(f"scope IN {RECOVERY_SCOPES!r}", name="ck_runtime_restore_executions_scope"),
        CheckConstraint(f"status IN {RESTORE_EXECUTION_STATUSES!r}", name="ck_runtime_restore_executions_status"),
        CheckConstraint(
            f"restore_target_type IN {RESTORE_TARGET_TYPES!r}",
            name="ck_runtime_restore_executions_target_type",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_restore_executions_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_restore_executions_result_hash"
        ),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_restore_executions_scope_org",
        ),
        CheckConstraint(
            "restore_target_type <> 'existing_environment' OR destructive_operation = true",
            name="ck_runtime_restore_existing_destructive",
        ),
        Index("ix_runtime_restore_executions_scope", "scope", "organization_id", "status", "requested_at"),
        Index("ix_runtime_restore_executions_backup", "backup_execution_id", "status"),
        Index("ix_runtime_restore_executions_correlation", "correlation_id"),
        Index(
            "uq_runtime_restore_execution_platform_idempotency",
            "scope",
            "provider_type",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_restore_execution_org_idempotency",
            "scope",
            "organization_id",
            "provider_type",
            "input_hash",
            "idempotency_key",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.recovery_policies.id", name="fk_runtime_restore_execution_policy")
    )
    backup_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.backup_executions.id", name="fk_runtime_restore_execution_backup")
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_execution_id: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    restore_target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    restore_target_reference: Mapped[str | None] = mapped_column(String(255))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default="requested", nullable=False)
    database_restored: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    object_storage_restored: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    configuration_restored: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    destructive_operation: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RestoreVerification(Base):
    __tablename__ = "restore_verifications"
    __table_args__ = (
        CheckConstraint(f"status IN {RESTORE_VERIFICATION_STATUSES!r}", name="ck_runtime_restore_verifications_status"),
        CheckConstraint(
            "evidence_hash IS NULL OR length(evidence_hash) = 64", name="ck_runtime_restore_verifications_hash"
        ),
        Index("ix_runtime_restore_verifications_restore", "restore_execution_id", "status", "completed_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restore_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.restore_executions.id", name="fk_runtime_restore_verification_restore", ondelete="CASCADE"),
        nullable=False,
    )
    verification_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="pending", nullable=False)
    database_connectivity_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    schema_version_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    record_counts_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    object_storage_access_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    artifact_checksums_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    organization_isolation_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    knowledge_lineage_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    enterprise_search_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    conversation_persistence_verified: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    document_registration_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    assistant_runtime_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    audit_runtime_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    verification_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    verified_by: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RecoveryEvidence(Base):
    __tablename__ = "recovery_evidence"
    __table_args__ = (
        CheckConstraint(f"scope IN {RECOVERY_SCOPES!r}", name="ck_runtime_recovery_evidence_scope"),
        CheckConstraint(f"status IN {RECOVERY_EVIDENCE_STATUSES!r}", name="ck_runtime_recovery_evidence_status"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_recovery_evidence_hash"),
        CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_recovery_evidence_scope_org",
        ),
        UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "source_entity_type",
            "source_entity_id",
            name="uq_runtime_recovery_evidence_source",
        ),
        Index("ix_runtime_recovery_evidence_scope", "scope", "organization_id", "evidence_type", "status"),
        Index("ix_runtime_recovery_evidence_expiry", "expires_at", "status"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core.organizations.id"))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
