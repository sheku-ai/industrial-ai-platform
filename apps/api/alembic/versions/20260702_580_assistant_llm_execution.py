"""add assistant llm execution

Revision ID: 20260702_580
Revises: 20260702_570
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_580"
down_revision = "20260702_570"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_llm_executions",
        sa.Column("llm_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gateway_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_type", sa.String(length=64), server_default="local_mock", nullable=False),
        sa.Column("provider_name", sa.String(length=128), server_default="deterministic-local-mock", nullable=False),
        sa.Column("model_name", sa.String(length=128), server_default="deterministic-assistant-runtime-mock", nullable=False),
        sa.Column("execution_status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("execution_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("provider_called", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("provider_call_mode", sa.String(length=64), server_default="deterministic_local_mock", nullable=False),
        sa.Column("request_payload_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("raw_output_text", sa.Text(), nullable=True),
        sa.Column("raw_output_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("prompt_tokens_estimated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completion_tokens_estimated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tokens_estimated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("citation_verification_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("final_response_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tool_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("workflow_executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("external_action_called", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("autonomous_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("llm_execution_id", name="pk_ai_assistant_llm_executions"),
        sa.ForeignKeyConstraint(["gateway_id"], ["ai.assistant_llm_invocation_plans.gateway_id"], name="fk_ai_assistant_llm_executions_gateway", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_package_id"], ["ai.assistant_prompt_packages.prompt_package_id"], name="fk_ai_assistant_llm_executions_prompt", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_llm_executions_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_llm_executions_session", ondelete="SET NULL"),
        sa.CheckConstraint("execution_status IN ('prepared','completed','blocked','failed','disabled')", name="ck_ai_assistant_llm_executions_status"),
        sa.CheckConstraint("provider_call_mode IN ('deterministic_local_mock')", name="ck_ai_assistant_llm_executions_call_mode"),
        sa.CheckConstraint("prompt_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_prompt_tokens"),
        sa.CheckConstraint("completion_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_completion_tokens"),
        sa.CheckConstraint("total_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_total_tokens"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_assistant_llm_executions_latency"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_llm_executions_gateway", "assistant_llm_executions", ["gateway_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_llm_executions_prompt", "assistant_llm_executions", ["prompt_package_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_llm_executions_assistant", "assistant_llm_executions", ["assistant_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_llm_executions_assistant", table_name="assistant_llm_executions", schema="ai")
    op.drop_index("ix_ai_assistant_llm_executions_prompt", table_name="assistant_llm_executions", schema="ai")
    op.drop_index("ix_ai_assistant_llm_executions_gateway", table_name="assistant_llm_executions", schema="ai")
    op.drop_table("assistant_llm_executions", schema="ai")
