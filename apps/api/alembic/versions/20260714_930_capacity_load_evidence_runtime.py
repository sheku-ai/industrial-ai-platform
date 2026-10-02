"""add persistent capacity and load evidence runtime

Revision ID: 20260714_930
Revises: 20260714_920
Create Date: 2026-07-14 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_930"
down_revision = "20260714_920"
branch_labels = None
depends_on = None

SCHEMA = "runtime"
JSON = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", UUID, primary_key=True),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "capacity_profiles",
        *_identity_columns(),
        sa.Column("profile_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("configured_capacity", JSON, nullable=False),
        sa.Column("target_capacity", JSON, nullable=False),
        sa.Column("thresholds", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_max_age_hours", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_capacity_profiles_scope"),
        sa.CheckConstraint("status IN ('draft','active','inactive','retired')", name="ck_runtime_capacity_profiles_status"),
        sa.CheckConstraint("evidence_max_age_hours > 0", name="ck_runtime_capacity_profiles_evidence_age"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_capacity_profiles_scope_org"),
        sa.UniqueConstraint("scope", "organization_id", "profile_code", "version", name="uq_runtime_capacity_profile"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_profiles_scope", "capacity_profiles", ["scope", "organization_id", "status", "updated_at"], schema=SCHEMA)
    op.create_index("uq_runtime_capacity_profile_platform_identity", "capacity_profiles", ["profile_code", "version"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_capacity_profile_org_identity", "capacity_profiles", ["organization_id", "profile_code", "version"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL"))
    op.create_index("uq_runtime_capacity_profile_active_platform", "capacity_profiles", ["scope"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL AND status = 'active'"))
    op.create_index("uq_runtime_capacity_profile_active_org", "capacity_profiles", ["scope", "organization_id"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL AND status = 'active'"))

    op.create_table(
        "capacity_load_test_executions",
        *_identity_columns(),
        sa.Column("profile_id", UUID, sa.ForeignKey("runtime.capacity_profiles.id"), nullable=False),
        sa.Column("execution_name", sa.String(255), nullable=False),
        sa.Column("scenario", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("concurrent_requests", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("requests_planned", sa.Integer(), nullable=False),
        sa.Column("requests_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requests_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_metadata", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_capacity_load_scope"),
        sa.CheckConstraint("status IN ('pending','running','completed','failed','blocked','cancelled')", name="ck_runtime_capacity_load_status"),
        sa.CheckConstraint("concurrent_requests > 0 AND duration_seconds > 0 AND requests_planned > 0", name="ck_runtime_capacity_load_positive_plan"),
        sa.CheckConstraint("requests_completed >= 0 AND requests_failed >= 0", name="ck_runtime_capacity_load_nonnegative_results"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_capacity_load_scope_org"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_load_scope", "capacity_load_test_executions", ["scope", "organization_id", "status", "requested_at"], schema=SCHEMA)
    op.create_index("uq_runtime_capacity_load_platform_idempotency", "capacity_load_test_executions", ["idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_capacity_load_org_idempotency", "capacity_load_test_executions", ["organization_id", "idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL"))

    op.create_table(
        "capacity_load_test_results",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("load_test_execution_id", UUID, sa.ForeignKey("runtime.capacity_load_test_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(128), nullable=False),
        sa.Column("component", sa.String(128), nullable=False),
        sa.Column("observed_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("target_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("percentile_values", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("metric_code IN ('concurrent_requests','ingestion','search','assistant','queue','worker','storage','database')", name="ck_runtime_capacity_load_result_metric"),
        sa.CheckConstraint("observed_value >= 0 AND target_value >= 0 AND sample_count > 0", name="ck_runtime_capacity_load_result_values"),
        sa.UniqueConstraint("load_test_execution_id", "metric_code", name="uq_runtime_capacity_load_result_metric"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_load_results_execution", "capacity_load_test_results", ["load_test_execution_id", "metric_code"], schema=SCHEMA)

    op.create_table(
        "capacity_evaluations",
        *_identity_columns(),
        sa.Column("profile_id", UUID, sa.ForeignKey("runtime.capacity_profiles.id"), nullable=False),
        sa.Column("load_test_execution_id", UUID, sa.ForeignKey("runtime.capacity_load_test_executions.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("configured_capacity", JSON, nullable=False),
        sa.Column("observed_capacity", JSON, nullable=False),
        sa.Column("target_capacity", JSON, nullable=False),
        sa.Column("utilization", JSON, nullable=False),
        sa.Column("bottlenecks", JSON, nullable=False),
        sa.Column("blockers", JSON, nullable=False),
        sa.Column("warnings", JSON, nullable=False),
        sa.Column("recommendations", JSON, nullable=False),
        sa.Column("next_actions", JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("evidence_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_age_seconds", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_capacity_evaluations_scope"),
        sa.CheckConstraint("status IN ('running','passed','failed','blocked')", name="ck_runtime_capacity_evaluations_status"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_capacity_evaluations_scope_org"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_evaluations_scope", "capacity_evaluations", ["scope", "organization_id", "evaluated_at"], schema=SCHEMA)
    op.create_index("uq_runtime_capacity_evaluation_platform_idempotency", "capacity_evaluations", ["idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_capacity_evaluation_org_idempotency", "capacity_evaluations", ["organization_id", "idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL"))

    op.create_table(
        "capacity_findings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_code", sa.String(128), nullable=False),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("component", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved','accepted')", name="ck_runtime_capacity_findings_status"),
        sa.UniqueConstraint("evaluation_id", "finding_code", name="uq_runtime_capacity_finding"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_findings_evaluation", "capacity_findings", ["evaluation_id", "severity", "status"], schema=SCHEMA)

    op.create_table(
        "capacity_recommendations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", UUID, sa.ForeignKey("runtime.capacity_findings.id"), nullable=True),
        sa.Column("recommendation_code", sa.String(128), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("component", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open','accepted','implemented','dismissed')", name="ck_runtime_capacity_recommendations_status"),
        sa.UniqueConstraint("evaluation_id", "recommendation_code", name="uq_runtime_capacity_recommendation"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_recommendations_evaluation", "capacity_recommendations", ["evaluation_id", "priority", "status"], schema=SCHEMA)

    op.create_table(
        "capacity_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("load_test_execution_id", UUID, sa.ForeignKey("runtime.capacity_load_test_executions.id"), nullable=True),
        sa.Column("evidence_code", sa.String(128), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("source_runtime", sa.String(128), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("evidence_payload", JSON, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("evaluation_id", "evidence_code", "evidence_hash", name="uq_runtime_capacity_evidence"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_evidence_evaluation", "capacity_evidence", ["evaluation_id", "observed_at"], schema=SCHEMA)

    op.create_table(
        "capacity_trends",
        *_identity_columns(),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(128), nullable=False),
        sa.Column("observed_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("configured_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("target_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("utilization_ratio", sa.Numeric(12, 6), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_capacity_trends_scope"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_capacity_trends_scope_org"),
        sa.CheckConstraint("metric_code IN ('concurrent_requests','ingestion','search','assistant','queue','worker','storage','database')", name="ck_runtime_capacity_trends_metric"),
        sa.CheckConstraint("observed_value >= 0 AND configured_value >= 0 AND target_value >= 0 AND utilization_ratio >= 0", name="ck_runtime_capacity_trends_values"),
        sa.UniqueConstraint("evaluation_id", "metric_code", name="uq_runtime_capacity_trend_metric"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_trends_scope_metric", "capacity_trends", ["scope", "organization_id", "metric_code", "captured_at"], schema=SCHEMA)

    op.create_table(
        "capacity_acceptance",
        *_identity_columns(),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.capacity_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", UUID, sa.ForeignKey("runtime.capacity_profiles.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("gate_results", JSON, nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False),
        sa.Column("recommendation_count", sa.Integer(), nullable=False),
        sa.Column("evidence_age_seconds", sa.Integer(), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("accepted_by", sa.String(255), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('passed','failed','blocked','not_evaluated')", name="ck_runtime_capacity_acceptance_status"),
        sa.CheckConstraint("scope IN ('platform','organization')", name="ck_runtime_capacity_acceptance_scope_value"),
        sa.CheckConstraint("(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)", name="ck_runtime_capacity_acceptance_scope_org"),
        sa.CheckConstraint("blocker_count >= 0 AND recommendation_count >= 0 AND (evidence_age_seconds IS NULL OR evidence_age_seconds >= 0)", name="ck_runtime_capacity_acceptance_counts"),
        sa.UniqueConstraint("evaluation_id", name="uq_runtime_capacity_acceptance_evaluation"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_capacity_acceptance_scope", "capacity_acceptance", ["scope", "organization_id", "accepted_at"], schema=SCHEMA)

    op.execute("""
        INSERT INTO security.permissions (id, resource, action, description, created_at, updated_at)
        VALUES
          (gen_random_uuid(), 'platform.capacity', 'read', 'Read governed Capacity and Load evidence and readiness.', now(), now()),
          (gen_random_uuid(), 'platform.capacity', 'administer', 'Administer Capacity profiles, load evidence, and evaluations.', now(), now())
        ON CONFLICT (resource, action) DO NOTHING
    """)
    op.execute("""
        INSERT INTO security.role_permissions (id, role_id, permission_id, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), rp.role_id, target.id, now(), now()
        FROM security.role_permissions rp
        JOIN security.permissions source ON source.id = rp.permission_id
        CROSS JOIN security.permissions target
        WHERE source.resource = 'platform.production_acceptance'
          AND target.resource = 'platform.capacity'
          AND target.action = source.action
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM security.role_permissions WHERE permission_id IN (SELECT id FROM security.permissions WHERE resource = 'platform.capacity')")
    op.execute("DELETE FROM security.permissions WHERE resource = 'platform.capacity'")
    for table in (
        "capacity_acceptance",
        "capacity_trends",
        "capacity_evidence",
        "capacity_recommendations",
        "capacity_findings",
        "capacity_evaluations",
        "capacity_load_test_results",
        "capacity_load_test_executions",
        "capacity_profiles",
    ):
        op.drop_table(table, schema=SCHEMA)
