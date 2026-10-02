"""derived vector index runtime foundation

Revision ID: 20260702_460
Revises: 20260702_440
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_460"
down_revision = "20260702_440"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "vector_index_records",
        sa.Column("vector_index_id", UUID, nullable=False),
        sa.Column("embedding_id", UUID, nullable=False),
        sa.Column("knowledge_chunk_id", UUID, nullable=False),
        sa.Column("knowledge_document_id", UUID, nullable=False),
        sa.Column("index_name", sa.String(255), nullable=False),
        sa.Column("index_provider", sa.String(128), nullable=False),
        sa.Column("index_provider_type", sa.String(128), nullable=False),
        sa.Column("index_status", sa.String(32), server_default="planned", nullable=False),
        sa.Column("index_version", sa.String(128), nullable=False),
        sa.Column("vector_dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_hash", sa.String(128), nullable=True),
        sa.Column("external_index_id", sa.String(255), nullable=True),
        sa.Column("external_point_id", sa.String(255), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("runtime_metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("vector_index_id", name="pk_knowledge_vector_index_records"),
        sa.ForeignKeyConstraint(["embedding_id"], ["knowledge.embedding_records.embedding_id"], name="fk_knowledge_vector_index_records_embedding", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_chunk_id"], ["knowledge.chunks.id"], name="fk_knowledge_vector_index_records_chunk", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_document_id"], ["knowledge.documents.id"], name="fk_knowledge_vector_index_records_document", ondelete="CASCADE"),
        sa.UniqueConstraint("embedding_id", "index_name", "index_provider", "index_version", name="uq_knowledge_vector_index_records_embedding_index"),
        sa.CheckConstraint("index_status IN ('planned','prepared','indexed','failed','disabled')", name="ck_knowledge_vector_index_records_status"),
        sa.CheckConstraint("vector_dimensions >= 0", name="ck_knowledge_vector_index_records_dimensions"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_vector_index_records_embedding_id", "vector_index_records", ["embedding_id"], schema="knowledge")
    op.create_index("ix_knowledge_vector_index_records_chunk_id", "vector_index_records", ["knowledge_chunk_id"], schema="knowledge")
    op.create_index("ix_knowledge_vector_index_records_status", "vector_index_records", ["index_status"], schema="knowledge")
    op.create_index("ix_knowledge_vector_index_records_provider", "vector_index_records", ["index_provider"], schema="knowledge")
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_knowledge_vector_index_records_provider", table_name="vector_index_records", schema="knowledge")
    op.drop_index("ix_knowledge_vector_index_records_status", table_name="vector_index_records", schema="knowledge")
    op.drop_index("ix_knowledge_vector_index_records_chunk_id", table_name="vector_index_records", schema="knowledge")
    op.drop_index("ix_knowledge_vector_index_records_embedding_id", table_name="vector_index_records", schema="knowledge")
    op.drop_table("vector_index_records", schema="knowledge")
