"""add operational observability runtime

Revision ID: 20260711_860
Revises: 20260711_850
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260711_860"
down_revision = "20260711_850"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "operational_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("component_code", sa.String(length=128), nullable=False),
        sa.Column("component_type", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("runtime_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("health_status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("readiness_status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("capabilities", _jsonb(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("configuration_reference", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_components"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_operational_components_org"),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "component_code",
            "instance_id",
            name="uq_runtime_operational_components_identity",
        ),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_components_scope"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR "
            "(scope = 'organization' AND organization_id IS NOT NULL)",
            name="ck_runtime_operational_components_scope_org",
        ),
        sa.CheckConstraint(
            "component_type IN ('api','worker','scheduler','monitor','reconciler','database','object_storage',"
            "'queue','portal','external_service','other')",
            name="ck_runtime_operational_components_type",
        ),
        sa.CheckConstraint(
            "status IN ('unknown','starting','running','degraded','stopping','stopped','failed','unavailable')",
            name="ck_runtime_operational_components_status",
        ),
        sa.CheckConstraint(
            "health_status IN ('unknown','healthy','degraded','unhealthy')",
            name="ck_runtime_operational_components_health",
        ),
        sa.CheckConstraint(
            "readiness_status IN ('unknown','ready','not_ready','blocked')",
            name="ck_runtime_operational_components_readiness",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_components_scope",
        "operational_components",
        ["scope", "organization_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_components_type",
        "operational_components",
        ["component_type", "health_status", "readiness_status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_components_observed",
        "operational_components",
        ["observed_at"],
        schema="runtime",
    )

    op.create_table(
        "operational_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), server_default="info", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="normal", nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.String(length=255), nullable=True),
        sa.Column("expected_value", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("source_runtime", sa.String(length=128), nullable=True),
        sa.Column("source_entity_type", sa.String(length=128), nullable=True),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column("evidence_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_observations"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_operational_observations_org"),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["runtime.operational_components.id"],
            name="fk_runtime_operational_observations_component",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "component_id",
            "observation_type",
            "evidence_hash",
            name="uq_runtime_operational_observation",
        ),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_observations_scope"),
        sa.CheckConstraint(
            "observation_type IN ('heartbeat','health','readiness','throughput','latency','queue_depth','error_rate',"
            "'retry','lease','execution','storage','database','dependency','capacity','custom')",
            name="ck_runtime_operational_observations_type",
        ),
        sa.CheckConstraint(
            "severity IN ('info','warning','error','critical')",
            name="ck_runtime_operational_observations_severity",
        ),
        sa.CheckConstraint(
            "status IN ('normal','degraded','failed','blocked','unknown')",
            name="ck_runtime_operational_observations_status",
        ),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_operational_observations_expiry"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_observations_scope",
        "operational_observations",
        ["scope", "organization_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_observations_component",
        "operational_observations",
        ["component_id", "observed_at"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_observations_observed",
        "operational_observations",
        ["observed_at", "expires_at"],
        schema="runtime",
    )

    op.create_table(
        "operational_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_type", sa.String(length=64), nullable=False),
        sa.Column("execution_reference", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_executions"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_operational_executions_org"),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["runtime.operational_components.id"],
            name="fk_runtime_operational_executions_component",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "execution_type",
            "idempotency_key",
            name="uq_runtime_operational_executions_idempotency",
        ),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_executions_scope"),
        sa.CheckConstraint(
            "execution_type IN ('scheduled_job','worker_job','reconciliation','monitoring_check','maintenance_action',"
            "'recovery_action','manual_operation','other')",
            name="ck_runtime_operational_executions_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','claimed','running','completed','failed','blocked','cancelled','abandoned')",
            name="ck_runtime_operational_executions_status",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_runtime_operational_executions_attempt"),
        sa.CheckConstraint("max_attempts > 0", name="ck_runtime_operational_executions_max_attempts"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_operational_executions_input_hash"),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_runtime_operational_executions_result_hash",
        ),
        schema="runtime",
    )
    op.create_index("ix_runtime_operational_executions_scope", "operational_executions", ["scope", "organization_id", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_executions_component", "operational_executions", ["component_id", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_executions_requested", "operational_executions", ["requested_at", "status"], schema="runtime")

    op.create_table(
        "operational_retry_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operational_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("retry_policy_code", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="scheduled", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delay_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("evidence_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_retry_attempts"),
        sa.ForeignKeyConstraint(
            ["operational_execution_id"],
            ["runtime.operational_executions.id"],
            name="fk_runtime_operational_retry_attempts_execution",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "operational_execution_id",
            "attempt_number",
            name="uq_runtime_operational_retry_attempt",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','running','succeeded','failed','skipped','exhausted','cancelled')",
            name="ck_runtime_operational_retry_attempts_status",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_runtime_operational_retry_attempts_number"),
        sa.CheckConstraint("delay_seconds >= 0", name="ck_runtime_operational_retry_attempts_delay"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_retry_attempts_execution",
        "operational_retry_attempts",
        ["operational_execution_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_retry_attempts_scheduled",
        "operational_retry_attempts",
        ["scheduled_at", "status"],
        schema="runtime",
    )

    op.create_table(
        "operational_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("incident_code", sa.String(length=128), nullable=False),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operational_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_entity_type", sa.String(length=128), nullable=True),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolution_code", sa.String(length=128), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_incidents"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_operational_incidents_org"),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["runtime.operational_components.id"],
            name="fk_runtime_operational_incidents_component",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operational_execution_id"],
            ["runtime.operational_executions.id"],
            name="fk_runtime_operational_incidents_execution",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "incident_code",
            "source_entity_type",
            "source_entity_id",
            "status",
            name="uq_runtime_operational_incident_open_identity",
        ),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_incidents_scope"),
        sa.CheckConstraint("severity IN ('info','warning','error','critical')", name="ck_runtime_operational_incidents_severity"),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','recovering','resolved','suppressed')",
            name="ck_runtime_operational_incidents_status",
        ),
        sa.CheckConstraint("occurrence_count > 0", name="ck_runtime_operational_incidents_occurrence_count"),
        schema="runtime",
    )
    op.create_index("ix_runtime_operational_incidents_scope", "operational_incidents", ["scope", "organization_id", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_incidents_severity", "operational_incidents", ["severity", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_incidents_component", "operational_incidents", ["component_id", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_incidents_open", "operational_incidents", ["status", "severity", "last_observed_at"], schema="runtime")

    op.create_table(
        "operational_recovery_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operational_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="requested", nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("evidence_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_recovery_actions"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["runtime.operational_incidents.id"],
            name="fk_runtime_operational_recovery_actions_incident",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operational_execution_id"],
            ["runtime.operational_executions.id"],
            name="fk_runtime_operational_recovery_actions_execution",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("incident_id", "input_hash", "action_type", name="uq_runtime_operational_recovery_action"),
        sa.CheckConstraint(
            "action_type IN ('retry_execution','release_lease','reconcile_state','restart_component_request',"
            "'disable_schedule','enable_schedule','cancel_execution','mark_abandoned','manual_recovery','external_recovery')",
            name="ck_runtime_operational_recovery_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('requested','approved','running','completed','failed','blocked','cancelled')",
            name="ck_runtime_operational_recovery_actions_status",
        ),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_operational_recovery_actions_input_hash"),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_runtime_operational_recovery_actions_result_hash",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_recovery_actions_incident",
        "operational_recovery_actions",
        ["incident_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_operational_recovery_actions_status",
        "operational_recovery_actions",
        ["status", "requested_at"],
        schema="runtime",
    )

    op.create_table(
        "operational_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("evidence_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_type", sa.String(length=128), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_operational_evidence"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_operational_evidence_org"),
        sa.UniqueConstraint(
            "scope",
            "organization_id",
            "evidence_type",
            "source_entity_type",
            "source_entity_id",
            "evidence_hash",
            name="uq_runtime_operational_evidence_identity",
        ),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_operational_evidence_scope"),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')",
            name="ck_runtime_operational_evidence_status",
        ),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > observed_at", name="ck_runtime_operational_evidence_expiry"),
        schema="runtime",
    )
    op.create_index("ix_runtime_operational_evidence_scope", "operational_evidence", ["scope", "organization_id", "status"], schema="runtime")
    op.create_index("ix_runtime_operational_evidence_type", "operational_evidence", ["evidence_type", "observed_at"], schema="runtime")


def downgrade() -> None:
    op.drop_table("operational_evidence", schema="runtime")
    op.drop_table("operational_recovery_actions", schema="runtime")
    op.drop_table("operational_incidents", schema="runtime")
    op.drop_table("operational_retry_attempts", schema="runtime")
    op.drop_table("operational_executions", schema="runtime")
    op.drop_table("operational_observations", schema="runtime")
    op.drop_table("operational_components", schema="runtime")
