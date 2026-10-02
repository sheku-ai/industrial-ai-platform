"""add recovery evidence runtime

Revision ID: 20260711_850
Revises: 20260710_840
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260711_850"
down_revision = "20260710_840"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "recovery_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("database_backup_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("object_storage_backup_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("configuration_backup_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("backup_frequency", sa.String(length=128), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("retention_count", sa.Integer(), nullable=True),
        sa.Column("rpo_minutes", sa.Integer(), nullable=True),
        sa.Column("rto_minutes", sa.Integer(), nullable=True),
        sa.Column("verification_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("restore_test_frequency", sa.String(length=128), nullable=True),
        sa.Column("evidence_max_age_hours", sa.Integer(), nullable=True),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("configuration_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_recovery_policies"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_recovery_policies_org"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_recovery_policies_scope"),
        sa.CheckConstraint("status IN ('draft','active','inactive','retired')", name="ck_runtime_recovery_policies_status"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_recovery_policies_scope_org",
        ),
        sa.CheckConstraint("retention_days IS NULL OR retention_days > 0", name="ck_runtime_recovery_policies_retention_days"),
        sa.CheckConstraint("retention_count IS NULL OR retention_count > 0", name="ck_runtime_recovery_policies_retention_count"),
        sa.CheckConstraint("rpo_minutes IS NULL OR rpo_minutes > 0", name="ck_runtime_recovery_policies_rpo"),
        sa.CheckConstraint("rto_minutes IS NULL OR rto_minutes > 0", name="ck_runtime_recovery_policies_rto"),
        sa.CheckConstraint(
            "evidence_max_age_hours IS NULL OR evidence_max_age_hours > 0",
            name="ck_runtime_recovery_policies_evidence_age",
        ),
        schema="runtime",
    )
    op.create_index("ix_runtime_recovery_policies_scope", "recovery_policies", ["scope", "organization_id", "status"], schema="runtime")
    op.create_index(
        "uq_runtime_recovery_policy_active_platform",
        "recovery_policies",
        ["scope"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NULL AND status = 'active'"),
    )
    op.create_index(
        "uq_runtime_recovery_policy_active_org",
        "recovery_policies",
        ["scope", "organization_id"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("organization_id IS NOT NULL AND status = 'active'"),
    )

    op.create_table(
        "backup_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("provider_execution_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("backup_type", sa.String(length=32), nullable=False),
        sa.Column("database_included", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("object_storage_included", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("configuration_included", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("consistent_snapshot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("artifact_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=128), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_backup_executions"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_backup_executions_org"),
        sa.ForeignKeyConstraint(["policy_id"], ["runtime.recovery_policies.id"], name="fk_runtime_backup_execution_policy"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_backup_executions_scope"),
        sa.CheckConstraint("status IN ('pending','running','completed','failed','cancelled','blocked')", name="ck_runtime_backup_executions_status"),
        sa.CheckConstraint("backup_type IN ('full','incremental','differential','snapshot','external')", name="ck_runtime_backup_executions_type"),
        sa.CheckConstraint("artifact_count >= 0", name="ck_runtime_backup_executions_artifact_count"),
        sa.CheckConstraint("total_size_bytes IS NULL OR total_size_bytes >= 0", name="ck_runtime_backup_executions_size"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_backup_executions_input_hash"),
        sa.CheckConstraint("result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_backup_executions_result_hash"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_backup_executions_scope_org",
        ),
        schema="runtime",
    )
    op.create_index("ix_runtime_backup_executions_scope", "backup_executions", ["scope", "organization_id", "status", "requested_at"], schema="runtime")
    op.create_index("ix_runtime_backup_executions_policy", "backup_executions", ["policy_id", "status", "completed_at"], schema="runtime")
    op.create_index("uq_runtime_backup_execution_platform_idempotency", "backup_executions", ["scope", "provider_type", "input_hash", "idempotency_key"], unique=True, schema="runtime", postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_backup_execution_org_idempotency", "backup_executions", ["scope", "organization_id", "provider_type", "input_hash", "idempotency_key"], unique=True, schema="runtime", postgresql_where=sa.text("organization_id IS NOT NULL"))

    op.create_table(
        "backup_artifact_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("backup_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("storage_location_masked", sa.String(length=1024), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_algorithm", sa.String(length=64), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("encryption_status", sa.String(length=64), nullable=True),
        sa.Column("compression_status", sa.String(length=64), nullable=True),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("metadata_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_backup_artifact_evidence"),
        sa.ForeignKeyConstraint(["backup_execution_id"], ["runtime.backup_executions.id"], name="fk_runtime_backup_artifact_execution", ondelete="CASCADE"),
        sa.CheckConstraint("resource_type IN ('postgresql','object_storage','application_configuration','migration_manifest','release_manifest','other')", name="ck_runtime_backup_artifact_resource_type"),
        sa.CheckConstraint("verification_status IN ('pending','verified','failed','not_supported')", name="ck_runtime_backup_artifact_verification_status"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_backup_artifact_size"),
        schema="runtime",
    )
    op.create_index("ix_runtime_backup_artifact_execution", "backup_artifact_evidence", ["backup_execution_id", "resource_type"], schema="runtime")

    op.create_table(
        "restore_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("backup_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("provider_execution_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("restore_target_type", sa.String(length=64), nullable=False),
        sa.Column("restore_target_reference", sa.String(length=255), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="requested", nullable=False),
        sa.Column("database_restored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("object_storage_restored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("configuration_restored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destructive_operation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_restore_executions"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_restore_executions_org"),
        sa.ForeignKeyConstraint(["policy_id"], ["runtime.recovery_policies.id"], name="fk_runtime_restore_execution_policy"),
        sa.ForeignKeyConstraint(["backup_execution_id"], ["runtime.backup_executions.id"], name="fk_runtime_restore_execution_backup"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_restore_executions_scope"),
        sa.CheckConstraint("status IN ('requested','approved','running','completed','failed','cancelled','blocked')", name="ck_runtime_restore_executions_status"),
        sa.CheckConstraint("restore_target_type IN ('isolated_validation_environment','replacement_environment','existing_environment','external_target')", name="ck_runtime_restore_executions_target_type"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_restore_executions_input_hash"),
        sa.CheckConstraint("result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_restore_executions_result_hash"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_restore_executions_scope_org"),
        sa.CheckConstraint("restore_target_type <> 'existing_environment' OR destructive_operation = true", name="ck_runtime_restore_existing_destructive"),
        schema="runtime",
    )
    op.create_index("ix_runtime_restore_executions_scope", "restore_executions", ["scope", "organization_id", "status", "requested_at"], schema="runtime")
    op.create_index("ix_runtime_restore_executions_backup", "restore_executions", ["backup_execution_id", "status"], schema="runtime")
    op.create_index("uq_runtime_restore_execution_platform_idempotency", "restore_executions", ["scope", "provider_type", "input_hash", "idempotency_key"], unique=True, schema="runtime", postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_restore_execution_org_idempotency", "restore_executions", ["scope", "organization_id", "provider_type", "input_hash", "idempotency_key"], unique=True, schema="runtime", postgresql_where=sa.text("organization_id IS NOT NULL"))

    op.create_table(
        "restore_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restore_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("database_connectivity_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("schema_version_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("record_counts_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("object_storage_access_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("artifact_checksums_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("organization_isolation_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("knowledge_lineage_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enterprise_search_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("conversation_persistence_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verification_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("verified_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_restore_verifications"),
        sa.ForeignKeyConstraint(["restore_execution_id"], ["runtime.restore_executions.id"], name="fk_runtime_restore_verification_restore", ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending','running','passed','failed','blocked')", name="ck_runtime_restore_verifications_status"),
        sa.CheckConstraint("evidence_hash IS NULL OR length(evidence_hash) = 64", name="ck_runtime_restore_verifications_hash"),
        schema="runtime",
    )
    op.create_index("ix_runtime_restore_verifications_restore", "restore_verifications", ["restore_execution_id", "status", "completed_at"], schema="runtime")

    op.create_table(
        "recovery_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("evidence_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_recovery_evidence"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_recovery_evidence_org"),
        sa.UniqueConstraint("scope", "organization_id", "evidence_type", "source_entity_type", "source_entity_id", name="uq_runtime_recovery_evidence_source"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_recovery_evidence_scope"),
        sa.CheckConstraint("status IN ('passed','failed','blocked','not_evaluated')", name="ck_runtime_recovery_evidence_status"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_recovery_evidence_hash"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_recovery_evidence_scope_org"),
        schema="runtime",
    )
    op.create_index("ix_runtime_recovery_evidence_scope", "recovery_evidence", ["scope", "organization_id", "evidence_type", "status"], schema="runtime")
    op.create_index("ix_runtime_recovery_evidence_expiry", "recovery_evidence", ["expires_at", "status"], schema="runtime")


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_runtime_recovery_evidence_expiry", "recovery_evidence"),
        ("ix_runtime_recovery_evidence_scope", "recovery_evidence"),
    ):
        op.drop_index(index_name, table_name=table_name, schema="runtime")
    op.drop_table("recovery_evidence", schema="runtime")
    op.drop_index("ix_runtime_restore_verifications_restore", table_name="restore_verifications", schema="runtime")
    op.drop_table("restore_verifications", schema="runtime")
    for index_name in (
        "uq_runtime_restore_execution_org_idempotency",
        "uq_runtime_restore_execution_platform_idempotency",
        "ix_runtime_restore_executions_backup",
        "ix_runtime_restore_executions_scope",
    ):
        op.drop_index(index_name, table_name="restore_executions", schema="runtime")
    op.drop_table("restore_executions", schema="runtime")
    op.drop_index("ix_runtime_backup_artifact_execution", table_name="backup_artifact_evidence", schema="runtime")
    op.drop_table("backup_artifact_evidence", schema="runtime")
    for index_name in (
        "uq_runtime_backup_execution_org_idempotency",
        "uq_runtime_backup_execution_platform_idempotency",
        "ix_runtime_backup_executions_policy",
        "ix_runtime_backup_executions_scope",
    ):
        op.drop_index(index_name, table_name="backup_executions", schema="runtime")
    op.drop_table("backup_executions", schema="runtime")
    for index_name in (
        "uq_runtime_recovery_policy_active_org",
        "uq_runtime_recovery_policy_active_platform",
        "ix_runtime_recovery_policies_scope",
    ):
        op.drop_index(index_name, table_name="recovery_policies", schema="runtime")
    op.drop_table("recovery_policies", schema="runtime")
