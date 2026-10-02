"""add workflow runtime foundation

Revision ID: 20260702_500
Revises: 20260702_490
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_500"
down_revision = "20260702_490"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_name", sa.String(length=255), nullable=False),
        sa.Column("workflow_key", sa.String(length=128), nullable=False),
        sa.Column("workflow_status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("workflow_version", sa.String(length=64), server_default="1.0", nullable=False),
        sa.Column("workflow_type", sa.String(length=128), server_default="platform_runtime", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workflow_id", name="pk_runtime_workflows"),
        sa.UniqueConstraint("workflow_key", "workflow_version", name="uq_runtime_workflows_key_version"),
        sa.CheckConstraint("workflow_status IN ('draft','prepared','active','disabled','failed')", name="ck_runtime_workflows_status"),
        schema="runtime",
    )
    op.create_index("ix_runtime_workflows_key", "workflows", ["workflow_key"], schema="runtime")
    op.create_index("ix_runtime_workflows_status", "workflows", ["workflow_status"], schema="runtime")
    op.create_table(
        "workflow_steps",
        sa.Column("workflow_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=128), nullable=False),
        sa.Column("step_status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("runtime_domain", sa.String(length=64), nullable=False),
        sa.Column("runtime_action", sa.String(length=128), nullable=False),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workflow_step_id", name="pk_runtime_workflow_steps"),
        sa.ForeignKeyConstraint(["workflow_id"], ["runtime.workflows.workflow_id"], name="fk_runtime_workflow_steps_workflow", ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_id", "step_key", name="uq_runtime_workflow_steps_key"),
        sa.UniqueConstraint("workflow_id", "step_order", name="uq_runtime_workflow_steps_order"),
        sa.CheckConstraint("step_order >= 0", name="ck_runtime_workflow_steps_order"),
        sa.CheckConstraint("step_status IN ('draft','prepared','active','disabled','failed')", name="ck_runtime_workflow_steps_status"),
        schema="runtime",
    )
    op.create_index("ix_runtime_workflow_steps_workflow", "workflow_steps", ["workflow_id", "step_order"], schema="runtime")
    op.create_index("ix_runtime_workflow_steps_domain", "workflow_steps", ["runtime_domain"], schema="runtime")
    op.create_table(
        "workflow_runs",
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_status", sa.String(length=32), server_default="planned", nullable=False),
        sa.Column("execution_state", sa.String(length=32), server_default="metadata_only", nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workflow_run_id", name="pk_runtime_workflow_runs"),
        sa.ForeignKeyConstraint(["workflow_id"], ["runtime.workflows.workflow_id"], name="fk_runtime_workflow_runs_workflow", ondelete="CASCADE"),
        sa.CheckConstraint("run_status IN ('prepared','planned','completed','failed','blocked','disabled')", name="ck_runtime_workflow_runs_status"),
        sa.CheckConstraint("execution_state IN ('metadata_only','planned','completed','failed','blocked','disabled')", name="ck_runtime_workflow_runs_execution_state"),
        schema="runtime",
    )
    op.create_index("ix_runtime_workflow_runs_workflow", "workflow_runs", ["workflow_id", "created_at"], schema="runtime")
    op.create_index("ix_runtime_workflow_runs_status", "workflow_runs", ["run_status"], schema="runtime")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_runtime_workflow_runs_status", table_name="workflow_runs", schema="runtime")
    op.drop_index("ix_runtime_workflow_runs_workflow", table_name="workflow_runs", schema="runtime")
    op.drop_table("workflow_runs", schema="runtime")
    op.drop_index("ix_runtime_workflow_steps_domain", table_name="workflow_steps", schema="runtime")
    op.drop_index("ix_runtime_workflow_steps_workflow", table_name="workflow_steps", schema="runtime")
    op.drop_table("workflow_steps", schema="runtime")
    op.drop_index("ix_runtime_workflows_status", table_name="workflows", schema="runtime")
    op.drop_index("ix_runtime_workflows_key", table_name="workflows", schema="runtime")
    op.drop_table("workflows", schema="runtime")
