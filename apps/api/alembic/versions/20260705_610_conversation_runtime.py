"""add conversation runtime

Revision ID: 20260705_610
Revises: 20260705_600
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_610"
down_revision = "20260705_600"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("conversation_title", sa.String(length=255), nullable=True),
        sa.Column("conversation_reference", sa.String(length=255), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("runtime_context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("conversation_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id", name="pk_ai_conversations"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_conversations_assistant", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_conversations_session", ondelete="SET NULL"),
        sa.CheckConstraint("conversation_status IN ('active','completed','archived','blocked','failed','disabled')", name="ck_ai_conversations_status"),
        schema="ai",
    )
    op.create_index("ix_ai_conversations_assistant", "conversations", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_conversations_session", "conversations", ["assistant_session_id", "created_at"], schema="ai")
    op.create_index("ix_ai_conversations_status", "conversations", ["conversation_status"], schema="ai")
    op.create_index("ix_ai_conversations_reference", "conversations", ["conversation_reference"], schema="ai")
    op.create_table(
        "conversation_turns",
        sa.Column("conversation_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_response_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("turn_role", sa.String(length=32), nullable=False),
        sa.Column("turn_status", sa.String(length=32), server_default="recorded", nullable=False),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("response_format", sa.String(length=64), server_default="markdown", nullable=False),
        sa.Column("citation_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("ordered_citations", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("turn_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_turn_id", name="pk_ai_conversation_turns"),
        sa.UniqueConstraint("conversation_id", "turn_index", name="uq_ai_conversation_turns_conversation_index"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai.conversations.conversation_id"], name="fk_ai_conversation_turns_conversation", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_id"], ["ai.assistant_definitions.assistant_id"], name="fk_ai_conversation_turns_assistant", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_session_id"], ["ai.assistant_sessions.assistant_session_id"], name="fk_ai_conversation_turns_session", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_run_id"], ["ai.assistant_runtime_runs.assistant_run_id"], name="fk_ai_conversation_turns_assistant_run", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_response_id"], ["ai.assistant_responses.assistant_response_id"], name="fk_ai_conversation_turns_response", ondelete="SET NULL"),
        sa.CheckConstraint("turn_index >= 0", name="ck_ai_conversation_turns_index"),
        sa.CheckConstraint("turn_role IN ('user','assistant','system','tool')", name="ck_ai_conversation_turns_role"),
        sa.CheckConstraint("turn_status IN ('recorded','completed','blocked','failed','disabled')", name="ck_ai_conversation_turns_status"),
        schema="ai",
    )
    op.create_index("ix_ai_conversation_turns_conversation", "conversation_turns", ["conversation_id", "turn_index"], schema="ai")
    op.create_index("ix_ai_conversation_turns_assistant", "conversation_turns", ["assistant_id", "created_at"], schema="ai")
    op.create_index("ix_ai_conversation_turns_assistant_run", "conversation_turns", ["assistant_run_id"], schema="ai")
    op.create_index("ix_ai_conversation_turns_response", "conversation_turns", ["assistant_response_id"], schema="ai")
    op.create_index("ix_ai_conversation_turns_role", "conversation_turns", ["turn_role"], schema="ai")
    op.create_index("ix_ai_conversation_turns_status", "conversation_turns", ["turn_status"], schema="ai")
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','assistant_response','conversation_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime','assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder','assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','assistant_response','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_ai_conversation_turns_status", table_name="conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversation_turns_role", table_name="conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversation_turns_response", table_name="conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversation_turns_assistant_run", table_name="conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversation_turns_assistant", table_name="conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversation_turns_conversation", table_name="conversation_turns", schema="ai")
    op.drop_table("conversation_turns", schema="ai")
    op.drop_index("ix_ai_conversations_reference", table_name="conversations", schema="ai")
    op.drop_index("ix_ai_conversations_status", table_name="conversations", schema="ai")
    op.drop_index("ix_ai_conversations_session", table_name="conversations", schema="ai")
    op.drop_index("ix_ai_conversations_assistant", table_name="conversations", schema="ai")
    op.drop_table("conversations", schema="ai")
