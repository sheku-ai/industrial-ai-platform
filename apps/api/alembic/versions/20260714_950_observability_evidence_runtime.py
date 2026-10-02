"""add observability evidence and health runtime

Revision ID: 20260714_950
Revises: 20260714_940
Create Date: 2026-07-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_950"
down_revision = "20260714_940"
branch_labels = None
depends_on = None

SCHEMA = "runtime"
UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("record_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _scope_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("scope IN ('platform','organization')", name=f"ck_runtime_observability_{prefix}_scope"),
        sa.CheckConstraint(
            "(scope = 'platform' AND organization_id IS NULL) OR (scope = 'organization' AND organization_id IS NOT NULL)",
            name=f"ck_runtime_observability_{prefix}_scope_org",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "observability_profiles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("profile_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("evidence_max_age_seconds", sa.Integer(), nullable=False),
        sa.Column("heartbeat_max_age_seconds", sa.Integer(), nullable=False),
        sa.Column("minimum_availability_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("minimum_signal_coverage_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("thresholds", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_scope_constraints("profile"),
        sa.CheckConstraint("status IN ('draft','active','inactive','retired')", name="ck_runtime_observability_profile_status"),
        sa.CheckConstraint("evidence_max_age_seconds > 0 AND heartbeat_max_age_seconds > 0", name="ck_runtime_observability_profile_freshness"),
        sa.CheckConstraint("minimum_availability_percentage BETWEEN 0 AND 100 AND minimum_signal_coverage_percentage BETWEEN 0 AND 100", name="ck_runtime_observability_profile_thresholds"),
        schema=SCHEMA,
    )
    op.create_index("uq_runtime_observability_profile_platform", "observability_profiles", ["profile_code", "version"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_observability_profile_org", "observability_profiles", ["organization_id", "profile_code", "version"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL"))
    op.create_index("uq_runtime_observability_profile_active_platform", "observability_profiles", ["scope"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL AND status = 'active'"))
    op.create_index("uq_runtime_observability_profile_active_org", "observability_profiles", ["scope", "organization_id"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL AND status = 'active'"))

    op.create_table(
        "observability_health_domains",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("profile_id", UUID, sa.ForeignKey("runtime.observability_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("domain_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("required_component_codes", JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        *_timestamps(),
        *_scope_constraints("domain"),
        sa.CheckConstraint("status IN ('active','inactive','degraded','failed','unknown')", name="ck_runtime_observability_domain_status"),
        sa.UniqueConstraint("profile_id", "domain_code", "version", name="uq_runtime_observability_domain"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_domain_scope", "observability_health_domains", ["scope", "organization_id", "status"], schema=SCHEMA)

    op.create_table(
        "observability_components",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("health_domain_id", UUID, sa.ForeignKey("runtime.observability_health_domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("component_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("component_type", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("required_signal_codes", JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("component_metadata", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        *_timestamps(),
        *_scope_constraints("component"),
        sa.CheckConstraint("status IN ('active','inactive','degraded','failed','unknown')", name="ck_runtime_observability_component_status"),
        sa.UniqueConstraint("health_domain_id", "component_code", "version", name="uq_runtime_observability_component"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_component_scope", "observability_components", ["scope", "organization_id", "status"], schema=SCHEMA)

    op.create_table(
        "observability_dependencies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("component_id", UUID, sa.ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependency_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dependency_type", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("critical", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("origin", sa.String(128), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','inactive','degraded','failed','unknown')", name="ck_runtime_observability_dependency_status"),
        sa.UniqueConstraint("component_id", "dependency_code", "version", name="uq_runtime_observability_dependency"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_dependency_component", "observability_dependencies", ["component_id", "status", "observed_at"], schema=SCHEMA)

    op.create_table(
        "observability_signals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("component_id", UUID, sa.ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_code", sa.String(128), nullable=False),
        sa.Column("signal_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("origin", sa.String(128), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("evidence_payload", JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('healthy','degraded','failed','unknown')", name="ck_runtime_observability_signal_status"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_signal_hash"),
        sa.UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_signal_idempotency"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_signal_component", "observability_signals", ["component_id", "signal_code", "observed_at"], schema=SCHEMA)

    op.create_table(
        "observability_heartbeats",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("component_id", UUID, sa.ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("origin", sa.String(128), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('healthy','degraded','failed')", name="ck_runtime_observability_heartbeat_status"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_heartbeat_hash"),
        sa.UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_heartbeat_idempotency"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_heartbeat_component", "observability_heartbeats", ["component_id", "observed_at"], schema=SCHEMA)

    op.create_table(
        "observability_availability_windows",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("component_id", UUID, sa.ForeignKey("runtime.observability_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_seconds", sa.Integer(), nullable=False),
        sa.Column("unavailable_seconds", sa.Integer(), nullable=False),
        sa.Column("availability_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("origin", sa.String(128), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("window_end > window_start", name="ck_runtime_observability_availability_window"),
        sa.CheckConstraint("availability_percentage BETWEEN 0 AND 100", name="ck_runtime_observability_availability_percentage"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_observability_availability_hash"),
        sa.UniqueConstraint("component_id", "idempotency_key", name="uq_runtime_observability_availability_idempotency"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_availability_component", "observability_availability_windows", ["component_id", "window_end"], schema=SCHEMA)

    op.create_table(
        "observability_health_evaluations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("profile_id", UUID, sa.ForeignKey("runtime.observability_profiles.id"), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("overall_health", sa.String(32), nullable=False),
        sa.Column("availability_status", sa.String(32), nullable=False),
        sa.Column("heartbeat_status", sa.String(32), nullable=False),
        sa.Column("signal_status", sa.String(32), nullable=False),
        sa.Column("dependency_status", sa.String(32), nullable=False),
        sa.Column("coverage_status", sa.String(32), nullable=False),
        sa.Column("freshness_status", sa.String(32), nullable=False),
        sa.Column("component_status", sa.String(32), nullable=False),
        sa.Column("acceptance_status", sa.String(32), nullable=False),
        sa.Column("availability_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("signal_coverage_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("evidence_age_seconds", sa.Integer(), nullable=True),
        sa.Column("blockers", JSON, nullable=False),
        sa.Column("warnings", JSON, nullable=False),
        sa.Column("recommendations", JSON, nullable=False),
        sa.Column("next_actions", JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        *_scope_constraints("evaluation"),
        sa.CheckConstraint("overall_health IN ('healthy','degraded','failed','blocked','not_evaluated')", name="ck_runtime_observability_evaluation_health"),
        schema=SCHEMA,
    )
    op.create_index("uq_runtime_observability_evaluation_platform_idempotency", "observability_health_evaluations", ["idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NULL"))
    op.create_index("uq_runtime_observability_evaluation_org_idempotency", "observability_health_evaluations", ["organization_id", "idempotency_key"], unique=True, schema=SCHEMA, postgresql_where=sa.text("organization_id IS NOT NULL"))
    op.create_index("ix_runtime_observability_evaluation_scope", "observability_health_evaluations", ["scope", "organization_id", "evaluated_at"], schema=SCHEMA)

    op.create_table(
        "observability_health_findings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_id", UUID, sa.ForeignKey("runtime.observability_components.id"), nullable=True),
        sa.Column("dependency_id", UUID, sa.ForeignKey("runtime.observability_dependencies.id"), nullable=True),
        sa.Column("finding_code", sa.String(160), nullable=False),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved','accepted')", name="ck_runtime_observability_finding_status"),
        sa.UniqueConstraint("evaluation_id", "finding_code", name="uq_runtime_observability_finding"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_finding_evaluation", "observability_health_findings", ["evaluation_id", "severity", "status"], schema=SCHEMA)

    op.create_table(
        "observability_health_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin", sa.String(128), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("evaluation_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_ids", JSON, nullable=False),
        sa.Column("dependency_ids", JSON, nullable=False),
        sa.Column("heartbeat_ids", JSON, nullable=False),
        sa.Column("signal_ids", JSON, nullable=False),
        sa.Column("finding_ids", JSON, nullable=False),
        sa.Column("evidence_payload", JSON, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_observability_evidence_hash"),
        sa.UniqueConstraint("evaluation_id", "evidence_hash", name="uq_runtime_observability_health_evidence"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_evidence_evaluation", "observability_health_evidence", ["evaluation_id", "evaluation_timestamp"], schema=SCHEMA)

    op.create_table(
        "observability_health_acceptance",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("gate_results", JSON, nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("evidence_age_seconds", sa.Integer(), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("accepted_by", sa.String(255), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        *_scope_constraints("acceptance"),
        sa.UniqueConstraint("evaluation_id", name="uq_runtime_observability_acceptance_evaluation"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_acceptance_scope", "observability_health_acceptance", ["scope", "organization_id", "accepted_at"], schema=SCHEMA)

    op.create_table(
        "observability_health_history",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("evaluation_id", UUID, sa.ForeignKey("runtime.observability_health_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID, sa.ForeignKey("core.organizations.id"), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("overall_health", sa.String(32), nullable=False),
        sa.Column("availability_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("signal_coverage_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("evidence_age_seconds", sa.Integer(), nullable=True),
        sa.Column("component_summary", JSON, nullable=False),
        sa.Column("dependency_summary", JSON, nullable=False),
        sa.Column("finding_summary", JSON, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        *_scope_constraints("history"),
        sa.UniqueConstraint("evaluation_id", name="uq_runtime_observability_history_evaluation"),
        schema=SCHEMA,
    )
    op.create_index("ix_runtime_observability_history_scope", "observability_health_history", ["scope", "organization_id", "captured_at"], schema=SCHEMA)

    op.execute("""
        INSERT INTO security.permissions (id, resource, action, description, created_at, updated_at)
        VALUES
          (gen_random_uuid(), 'platform.observability', 'read', 'Read persisted observability evidence and health readiness.', now(), now()),
          (gen_random_uuid(), 'platform.observability', 'administer', 'Administer observability profiles and persisted health evidence.', now(), now())
        ON CONFLICT (resource, action) DO NOTHING
    """)
    op.execute("""
        INSERT INTO security.role_permissions (id, role_id, permission_id, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), rp.role_id, target.id, now(), now()
        FROM security.role_permissions rp
        JOIN security.permissions source ON source.id = rp.permission_id
        CROSS JOIN security.permissions target
        WHERE source.resource = 'platform.production_acceptance'
          AND target.resource = 'platform.observability'
          AND target.action = source.action
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM security.role_permissions WHERE permission_id IN (SELECT id FROM security.permissions WHERE resource = 'platform.observability')")
    op.execute("DELETE FROM security.permissions WHERE resource = 'platform.observability'")
    for table in (
        "observability_health_history",
        "observability_health_acceptance",
        "observability_health_evidence",
        "observability_health_findings",
        "observability_health_evaluations",
        "observability_availability_windows",
        "observability_heartbeats",
        "observability_signals",
        "observability_dependencies",
        "observability_components",
        "observability_health_domains",
        "observability_profiles",
    ):
        op.drop_table(table, schema=SCHEMA)
