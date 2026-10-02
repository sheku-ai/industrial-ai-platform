"""add assistant response runtime

Revision ID: 20260705_600
Revises: 20260702_590
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_600"
down_revision = "20260702_590"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_responses",
        sa.Column("assistant_response_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_verification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("llm_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_format", sa.String(length=64), server_default="markdown", nullable=False),
        sa.Column("response_language", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("citation_verification_passed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("verified_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("missing_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("invalid_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ordered_citations", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("response_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("assistant_response_id", name="pk_ai_assistant_responses"),
        sa.ForeignKeyConstraint(["citation_verification_id"], ["ai.assistant_citation_verifications.citation_verification_id"], name="fk_ai_assistant_responses_citation_verification", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_execution_id"], ["ai.assistant_llm_executions.llm_execution_id"], name="fk_ai_assistant_responses_llm_execution", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_package_id"], ["ai.assistant_prompt_packages.prompt_package_id"], name="fk_ai_assistant_responses_prompt", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["context_package_id"], ["ai.assistant_context_packages.context_package_id"], name="fk_ai_assistant_responses_context", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_responses_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_responses_session", ondelete="SET NULL"),
        sa.CheckConstraint("response_status IN ('prepared','completed','blocked','failed','disabled')", name="ck_ai_assistant_responses_status"),
        sa.CheckConstraint("verified_citation_count >= 0", name="ck_ai_assistant_responses_verified_count"),
        sa.CheckConstraint("missing_citation_count >= 0", name="ck_ai_assistant_responses_missing_count"),
        sa.CheckConstraint("invalid_citation_count >= 0", name="ck_ai_assistant_responses_invalid_count"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_responses_citation_verification", "assistant_responses", ["citation_verification_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_responses_llm_execution", "assistant_responses", ["llm_execution_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_responses_assistant", "assistant_responses", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_responses_session", "assistant_responses", ["assistant_session_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','assistant_response','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_responses_session", table_name="assistant_responses", schema="ai")
    op.drop_index("ix_ai_assistant_responses_assistant", table_name="assistant_responses", schema="ai")
    op.drop_index("ix_ai_assistant_responses_llm_execution", table_name="assistant_responses", schema="ai")
    op.drop_index("ix_ai_assistant_responses_citation_verification", table_name="assistant_responses", schema="ai")
    op.drop_table("assistant_responses", schema="ai")
