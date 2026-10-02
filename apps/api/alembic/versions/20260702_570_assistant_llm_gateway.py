"""add assistant llm gateway

Revision ID: 20260702_570
Revises: 20260702_560
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_570"
down_revision = "20260702_560"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_llm_invocation_plans",
        sa.Column("gateway_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_type", sa.String(length=64), server_default="reference", nullable=False),
        sa.Column("provider_name", sa.String(length=128), server_default="metadata-only", nullable=False),
        sa.Column("model_name", sa.String(length=128), server_default="metadata-only", nullable=False),
        sa.Column("provider_ready", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("execution_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("blocked_reason", sa.String(length=255), server_default="execution_disabled", nullable=False),
        sa.Column("planned_temperature", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("planned_max_tokens", sa.Integer(), server_default=sa.text("1024"), nullable=False),
        sa.Column("planned_top_p", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("planned_stop_sequences", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("planned_seed", sa.Integer(), nullable=True),
        sa.Column("planned_timeout", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("llm_invoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("answer_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tool_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("workflow_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("external_action_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("autonomous_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gateway_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("gateway_id", name="pk_ai_assistant_llm_invocation_plans"),
        sa.ForeignKeyConstraint(["prompt_package_id"], ["ai.assistant_prompt_packages.prompt_package_id"], name="fk_ai_assistant_llm_invocation_plans_prompt", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_llm_invocation_plans_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_llm_invocation_plans_session", ondelete="SET NULL"),
        sa.CheckConstraint("planned_temperature >= 0", name="ck_ai_assistant_llm_invocation_plans_temperature"),
        sa.CheckConstraint("planned_max_tokens > 0", name="ck_ai_assistant_llm_invocation_plans_max_tokens"),
        sa.CheckConstraint("planned_top_p >= 0 AND planned_top_p <= 1", name="ck_ai_assistant_llm_invocation_plans_top_p"),
        sa.CheckConstraint("planned_timeout > 0", name="ck_ai_assistant_llm_invocation_plans_timeout"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_llm_invocation_plans_prompt", "assistant_llm_invocation_plans", ["prompt_package_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_llm_invocation_plans_assistant", "assistant_llm_invocation_plans", ["assistant_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_llm_invocation_plans_assistant", table_name="assistant_llm_invocation_plans", schema="ai")
    op.drop_index("ix_ai_assistant_llm_invocation_plans_prompt", table_name="assistant_llm_invocation_plans", schema="ai")
    op.drop_table("assistant_llm_invocation_plans", schema="ai")
