"""add assistant retrieval runtime foundation

Revision ID: 20260702_520
Revises: 20260702_510
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_520"
down_revision = "20260702_510"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_retrieval_plans",
        sa.Column("retrieval_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_status", sa.String(length=32), server_default="planned", nullable=False),
        sa.Column("requested_query", sa.Text(), nullable=True),
        sa.Column("selected_search_mode", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("selected_runtime_domain", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("execution_state", sa.String(length=32), server_default="metadata_only", nullable=False),
        sa.Column("enterprise_search_planned", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("semantic_search_planned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hybrid_search_planned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("retrieval_executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("retrieval_plan_id", name="pk_ai_assistant_retrieval_plans"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_retrieval_plans_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_retrieval_plans_session", ondelete="SET NULL"),
        sa.CheckConstraint("plan_status IN ('prepared','planned','completed','blocked','failed','disabled')", name="ck_ai_assistant_retrieval_plans_status"),
        sa.CheckConstraint("execution_state IN ('metadata_only','planned','completed','blocked','failed','disabled')", name="ck_ai_assistant_retrieval_plans_execution_state"),
        sa.CheckConstraint("selected_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')", name="ck_ai_assistant_retrieval_plans_search_mode"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_retrieval_plans_assistant", "assistant_retrieval_plans", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_retrieval_plans_session", "assistant_retrieval_plans", ["assistant_session_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_retrieval_plans_status", "assistant_retrieval_plans", ["plan_status"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_retrieval_plans_status", table_name="assistant_retrieval_plans", schema="ai")
    op.drop_index("ix_ai_assistant_retrieval_plans_session", table_name="assistant_retrieval_plans", schema="ai")
    op.drop_index("ix_ai_assistant_retrieval_plans_assistant", table_name="assistant_retrieval_plans", schema="ai")
    op.drop_table("assistant_retrieval_plans", schema="ai")
