"""optional embedding runtime foundation

Revision ID: 20260702_440
Revises: 20260701_410
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_440"
down_revision = "20260701_410"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "embedding_records",
        sa.Column("embedding_id", UUID, nullable=False),
        sa.Column("chunk_id", UUID, nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("embedding_hash", sa.String(128), nullable=True),
        sa.Column("embedding_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runtime_metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("embedding_id", name="pk_knowledge_embedding_records"),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge.chunks.id"], name="fk_knowledge_embedding_records_chunk", ondelete="CASCADE"),
        sa.UniqueConstraint("chunk_id", "model_name", "model_version", name="uq_knowledge_embedding_records_chunk_model"),
        sa.CheckConstraint("embedding_dimensions >= 0", name="ck_knowledge_embedding_records_dimensions"),
        sa.CheckConstraint("embedding_status IN ('pending','completed','failed')", name="ck_knowledge_embedding_records_status"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_embedding_records_chunk_id", "embedding_records", ["chunk_id"], schema="knowledge")
    op.create_index("ix_knowledge_embedding_records_status", "embedding_records", ["embedding_status"], schema="knowledge")
    op.create_index("ix_knowledge_embedding_records_model", "embedding_records", ["model_name", "model_version"], schema="knowledge")
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_knowledge_embedding_records_model", table_name="embedding_records", schema="knowledge")
    op.drop_index("ix_knowledge_embedding_records_status", table_name="embedding_records", schema="knowledge")
    op.drop_index("ix_knowledge_embedding_records_chunk_id", table_name="embedding_records", schema="knowledge")
    op.drop_table("embedding_records", schema="knowledge")
