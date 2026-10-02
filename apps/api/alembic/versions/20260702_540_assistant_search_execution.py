"""add assistant enterprise search execution

Revision ID: 20260702_540
Revises: 20260702_530
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_540"
down_revision = "20260702_530"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_search_executions",
        sa.Column("search_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("search_mode", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("runtime_domain", sa.String(length=64), server_default="enterprise_search", nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("search_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("search_duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lexical_search_used", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("postgresql_fts_used", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("semantic_search_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hybrid_search_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("qdrant_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reranking_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("llm_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("answer_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tool_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("workflow_executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("external_action_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("autonomous_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("execution_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("search_execution_id", name="pk_ai_assistant_search_executions"),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["ai.assistant_retrieval_execution_plans.execution_plan_id"], name="fk_ai_assistant_search_executions_execution_plan", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retrieval_plan_id"], ["ai.assistant_retrieval_plans.retrieval_plan_id"], name="fk_ai_assistant_search_executions_retrieval_plan", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_search_executions_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_search_executions_session", ondelete="SET NULL"),
        sa.CheckConstraint("search_mode IN ('enterprise_search')", name="ck_ai_assistant_search_executions_mode"),
        sa.CheckConstraint("runtime_domain IN ('enterprise_search')", name="ck_ai_assistant_search_executions_domain"),
        sa.CheckConstraint("search_duration_ms IS NULL OR search_duration_ms >= 0", name="ck_ai_assistant_search_executions_duration"),
        sa.CheckConstraint("result_count >= 0", name="ck_ai_assistant_search_executions_result_count"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_search_executions_execution_plan", "assistant_search_executions", ["execution_plan_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_search_executions_retrieval_plan", "assistant_search_executions", ["retrieval_plan_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_search_executions_assistant", "assistant_search_executions", ["assistant_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_search_executions_assistant", table_name="assistant_search_executions", schema="ai")
    op.drop_index("ix_ai_assistant_search_executions_retrieval_plan", table_name="assistant_search_executions", schema="ai")
    op.drop_index("ix_ai_assistant_search_executions_execution_plan", table_name="assistant_search_executions", schema="ai")
    op.drop_table("assistant_search_executions", schema="ai")
