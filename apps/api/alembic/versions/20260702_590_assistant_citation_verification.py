"""add assistant citation verification

Revision ID: 20260702_590
Revises: 20260702_580
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_590"
down_revision = "20260702_580"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_citation_verifications",
        sa.Column("citation_verification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_runtime_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("llm_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("verified_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("missing_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("invalid_citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("verification_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("citation_verification_id", name="pk_ai_assistant_citation_verifications"),
        sa.ForeignKeyConstraint(["assistant_runtime_id"], ["ai.assistant_runtime_runs.assistant_run_id"], name="fk_ai_assistant_citation_verifications_runtime", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["llm_execution_id"], ["ai.assistant_llm_executions.llm_execution_id"], name="fk_ai_assistant_citation_verifications_llm_execution", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_package_id"], ["ai.assistant_prompt_packages.prompt_package_id"], name="fk_ai_assistant_citation_verifications_prompt", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["context_package_id"], ["ai.assistant_context_packages.context_package_id"], name="fk_ai_assistant_citation_verifications_context", ondelete="CASCADE"),
        sa.CheckConstraint("verification_status IN ('prepared','completed','blocked','failed','disabled')", name="ck_ai_assistant_citation_verifications_status"),
        sa.CheckConstraint("verified_citation_count >= 0", name="ck_ai_assistant_citation_verifications_verified_count"),
        sa.CheckConstraint("missing_citation_count >= 0", name="ck_ai_assistant_citation_verifications_missing_count"),
        sa.CheckConstraint("invalid_citation_count >= 0", name="ck_ai_assistant_citation_verifications_invalid_count"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_citation_verifications_llm_execution", "assistant_citation_verifications", ["llm_execution_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_citation_verifications_prompt", "assistant_citation_verifications", ["prompt_package_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_citation_verifications_context", "assistant_citation_verifications", ["context_package_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_citation_verifications_context", table_name="assistant_citation_verifications", schema="ai")
    op.drop_index("ix_ai_assistant_citation_verifications_prompt", table_name="assistant_citation_verifications", schema="ai")
    op.drop_index("ix_ai_assistant_citation_verifications_llm_execution", table_name="assistant_citation_verifications", schema="ai")
    op.drop_table("assistant_citation_verifications", schema="ai")
