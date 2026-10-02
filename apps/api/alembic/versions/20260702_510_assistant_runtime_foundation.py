"""add assistant runtime foundation

Revision ID: 20260702_510
Revises: 20260702_500
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_510"
down_revision = "20260702_500"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_definitions",
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_key", sa.String(length=128), nullable=False),
        sa.Column("assistant_name", sa.String(length=255), nullable=False),
        sa.Column("assistant_status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("assistant_version", sa.String(length=64), server_default="1.0", nullable=False),
        sa.Column("assistant_type", sa.String(length=128), server_default="platform_assistant", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_search_mode", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("allowed_runtime_domains", postgresql.ARRAY(sa.String(length=64)), server_default=sa.text("ARRAY[]::varchar[]"), nullable=False),
        sa.Column("guardrail_profile", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("assistant_id", name="pk_ai_assistant_definitions"),
        sa.UniqueConstraint("assistant_key", "assistant_version", name="uq_ai_assistant_definitions_key_version"),
        sa.CheckConstraint("assistant_status IN ('draft','prepared','active','disabled','failed')", name="ck_ai_assistant_definitions_status"),
        sa.CheckConstraint("default_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')", name="ck_ai_assistant_definitions_search_mode"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_definitions_key", "assistant_definitions", ["assistant_key"], schema="ai")
    op.create_index("ix_ai_assistant_definitions_status", "assistant_definitions", ["assistant_status"], schema="ai")
    op.create_table(
        "assistant_sessions",
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("conversation_reference", sa.String(length=255), nullable=True),
        sa.Column("runtime_context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("assistant_session_id", name="pk_ai_assistant_sessions"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_sessions_assistant", ondelete="CASCADE"),
        sa.CheckConstraint("session_status IN ('prepared','planned','completed','blocked','failed','disabled')", name="ck_ai_assistant_sessions_status"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_sessions_assistant", "assistant_sessions", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_sessions_status", "assistant_sessions", ["session_status"], schema="ai")
    op.create_table(
        "assistant_runtime_runs",
        sa.Column("assistant_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_status", sa.String(length=32), server_default="planned", nullable=False),
        sa.Column("requested_query", sa.Text(), nullable=True),
        sa.Column("selected_search_mode", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("selected_runtime_domain", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("execution_state", sa.String(length=32), server_default="metadata_only", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("assistant_run_id", name="pk_ai_assistant_runtime_runs"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_runtime_runs_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_runtime_runs_session", ondelete="CASCADE"),
        sa.CheckConstraint("run_status IN ('prepared','planned','completed','blocked','failed','disabled')", name="ck_ai_assistant_runtime_runs_status"),
        sa.CheckConstraint("execution_state IN ('metadata_only','planned','completed','blocked','failed','disabled')", name="ck_ai_assistant_runtime_runs_execution_state"),
        sa.CheckConstraint("selected_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')", name="ck_ai_assistant_runtime_runs_search_mode"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_runtime_runs_assistant", "assistant_runtime_runs", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_runtime_runs_session", "assistant_runtime_runs", ["assistant_session_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_runtime_runs_status", "assistant_runtime_runs", ["run_status"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_runtime_runs_status", table_name="assistant_runtime_runs", schema="ai")
    op.drop_index("ix_ai_assistant_runtime_runs_session", table_name="assistant_runtime_runs", schema="ai")
    op.drop_index("ix_ai_assistant_runtime_runs_assistant", table_name="assistant_runtime_runs", schema="ai")
    op.drop_table("assistant_runtime_runs", schema="ai")
    op.drop_index("ix_ai_assistant_sessions_status", table_name="assistant_sessions", schema="ai")
    op.drop_index("ix_ai_assistant_sessions_assistant", table_name="assistant_sessions", schema="ai")
    op.drop_table("assistant_sessions", schema="ai")
    op.drop_index("ix_ai_assistant_definitions_status", table_name="assistant_definitions", schema="ai")
    op.drop_index("ix_ai_assistant_definitions_key", table_name="assistant_definitions", schema="ai")
    op.drop_table("assistant_definitions", schema="ai")
