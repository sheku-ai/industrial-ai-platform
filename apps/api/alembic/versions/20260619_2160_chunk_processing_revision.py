"""link chunks to processing revisions additively

Revision ID: 20260619_2160
Revises: 20260619_2150
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260619_2160"
down_revision: str | None = "20260619_2150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("processing_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="documents",
    )
    op.create_foreign_key(
        "fk_chunks_processing_revision_id",
        "chunks",
        "processing_revisions",
        ["processing_revision_id"],
        ["id"],
        source_schema="documents",
        referent_schema="documents",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_chunks_processing_revision_id",
        "chunks",
        ["processing_revision_id"],
        schema="documents",
    )
    op.create_index(
        "uq_chunks_revision_chunk_key",
        "chunks",
        ["organization_id", "processing_revision_id", "chunk_key"],
        unique=True,
        schema="documents",
        postgresql_where=sa.text("processing_revision_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_chunks_revision_chunk_key", table_name="chunks", schema="documents")
    op.drop_index("ix_chunks_processing_revision_id", table_name="chunks", schema="documents")
    op.drop_constraint(
        "fk_chunks_processing_revision_id",
        "chunks",
        schema="documents",
        type_="foreignkey",
    )
    op.drop_column("chunks", "processing_revision_id", schema="documents")
