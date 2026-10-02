"""add assistant prompt assembly

Revision ID: 20260702_560
Revises: 20260702_550
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_560"
down_revision = "20260702_550"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_prompt_packages",
        sa.Column("prompt_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("package_status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("assistant_instructions", sa.Text(), nullable=False),
        sa.Column("assembled_context", sa.Text(), nullable=False),
        sa.Column("citation_section", sa.Text(), nullable=False),
        sa.Column("estimated_prompt_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("prompt_size_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("prompt_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("llm_ready", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("llm_invoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("answer_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("prompt_package_id", name="pk_ai_assistant_prompt_packages"),
        sa.ForeignKeyConstraint(["context_package_id"], ["ai.assistant_context_packages.context_package_id"], name="fk_ai_assistant_prompt_packages_context", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_prompt_packages_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_prompt_packages_session", ondelete="SET NULL"),
        sa.CheckConstraint("package_status IN ('prepared','created','blocked','failed','disabled')", name="ck_ai_assistant_prompt_packages_status"),
        sa.CheckConstraint("estimated_prompt_tokens >= 0", name="ck_ai_assistant_prompt_packages_tokens"),
        sa.CheckConstraint("prompt_size_bytes >= 0", name="ck_ai_assistant_prompt_packages_size"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_prompt_packages_context", "assistant_prompt_packages", ["context_package_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_prompt_packages_assistant", "assistant_prompt_packages", ["assistant_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_prompt_packages_assistant", table_name="assistant_prompt_packages", schema="ai")
    op.drop_index("ix_ai_assistant_prompt_packages_context", table_name="assistant_prompt_packages", schema="ai")
    op.drop_table("assistant_prompt_packages", schema="ai")
