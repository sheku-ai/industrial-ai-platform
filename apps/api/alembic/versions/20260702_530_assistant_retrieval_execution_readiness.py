"""add assistant retrieval execution readiness

Revision ID: 20260702_530
Revises: 20260702_520
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_530"
down_revision = "20260702_520"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_retrieval_execution_plans",
        sa.Column("execution_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("selected_search_mode", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("selected_runtime_domain", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("execution_state", sa.String(length=32), server_default="readiness_only", nullable=False),
        sa.Column("enterprise_search_execution_prepared", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("semantic_search_execution_prepared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hybrid_search_execution_prepared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("retrieval_executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("answer_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("llm_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tool_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("workflow_executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("external_action_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("autonomous_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("readiness_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("execution_plan_id", name="pk_ai_assistant_retrieval_execution_plans"),
        sa.ForeignKeyConstraint(["retrieval_plan_id"], ["ai.assistant_retrieval_plans.retrieval_plan_id"], name="fk_ai_assistant_retrieval_execution_plans_retrieval", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_retrieval_execution_plans_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_retrieval_execution_plans_session", ondelete="SET NULL"),
        sa.CheckConstraint("execution_status IN ('prepared','blocked','failed','disabled')", name="ck_ai_assistant_retrieval_execution_plans_status"),
        sa.CheckConstraint("execution_state IN ('readiness_only','blocked','failed','disabled')", name="ck_ai_assistant_retrieval_execution_plans_state"),
        sa.CheckConstraint("selected_search_mode IN ('enterprise_search','semantic_search','hybrid_search')", name="ck_ai_assistant_retrieval_execution_plans_search_mode"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_retrieval_execution_plans_retrieval", "assistant_retrieval_execution_plans", ["retrieval_plan_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_retrieval_execution_plans_assistant", "assistant_retrieval_execution_plans", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_retrieval_execution_plans_status", "assistant_retrieval_execution_plans", ["execution_status"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_retrieval_execution_plans_status", table_name="assistant_retrieval_execution_plans", schema="ai")
    op.drop_index("ix_ai_assistant_retrieval_execution_plans_assistant", table_name="assistant_retrieval_execution_plans", schema="ai")
    op.drop_index("ix_ai_assistant_retrieval_execution_plans_retrieval", table_name="assistant_retrieval_execution_plans", schema="ai")
    op.drop_table("assistant_retrieval_execution_plans", schema="ai")
