from alembic import op
import sqlalchemy as sa


revision = "20260623_25113"
down_revision = "20260622_2506b3"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_chunks_null_revision_chunk_key"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "chunks",
        ["organization_id", "document_version_id", "chunk_key"],
        unique=True,
        schema="documents",
        postgresql_where=sa.text("processing_revision_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chunks", schema="documents")
