"""add assistant context builder

Revision ID: 20260702_550
Revises: 20260702_540
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_550"
down_revision = "20260702_540"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "assistant_context_packages",
        sa.Column("context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("search_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("package_status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("citation_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tokens_estimated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("context_size_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("truncation_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("truncation_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ordered_context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("ordered_citations", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("package_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("context_package_id", name="pk_ai_assistant_context_packages"),
        sa.ForeignKeyConstraint(["search_execution_id"], ["ai.assistant_search_executions.search_execution_id"], name="fk_ai_assistant_context_packages_search_execution", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_assistant_context_packages_assistant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_assistant_context_packages_session", ondelete="SET NULL"),
        sa.CheckConstraint("package_status IN ('prepared','created','blocked','failed','disabled')", name="ck_ai_assistant_context_packages_status"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_ai_assistant_context_packages_chunk_count"),
        sa.CheckConstraint("citation_count >= 0", name="ck_ai_assistant_context_packages_citation_count"),
        sa.CheckConstraint("total_tokens_estimated >= 0", name="ck_ai_assistant_context_packages_tokens"),
        sa.CheckConstraint("context_size_bytes >= 0", name="ck_ai_assistant_context_packages_size"),
        schema="ai",
    )
    op.create_index("ix_ai_assistant_context_packages_search_execution", "assistant_context_packages", ["search_execution_id", "created_at"], schema="ai")
    op.create_index("ix_ai_assistant_context_packages_assistant", "assistant_context_packages", ["assistant_id", "created_at"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_assistant_context_packages_assistant", table_name="assistant_context_packages", schema="ai")
    op.drop_index("ix_ai_assistant_context_packages_search_execution", table_name="assistant_context_packages", schema="ai")
    op.drop_table("assistant_context_packages", schema="ai")
