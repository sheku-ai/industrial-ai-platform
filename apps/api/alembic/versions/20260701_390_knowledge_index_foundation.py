"""knowledge index foundation

Revision ID: 20260701_390
Revises: 20260701_360
Create Date: 2026-07-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260701_390"
down_revision: Union[str, None] = "20260701_360"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.create_table(
        "documents",
        sa.Column("id", UUID, nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("document_record_id", sa.String(128), nullable=True),
        sa.Column("document_version_id", sa.String(128), nullable=True),
        sa.Column("publication_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="indexed", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_signature", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_documents"),
        sa.UniqueConstraint("artifact_id", "publication_id", name="uq_knowledge_documents_artifact_publication"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_documents_artifact_id", "documents", ["artifact_id"], schema="knowledge")
    op.create_index("ix_knowledge_documents_publication_id", "documents", ["publication_id"], schema="knowledge")
    op.create_index("ix_knowledge_documents_status", "documents", ["status"], schema="knowledge")
    op.create_table(
        "chunks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("knowledge_document_id", UUID, nullable=False),
        sa.Column("published_chunk_id", sa.String(255), nullable=False),
        sa.Column("publication_id", sa.String(255), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("semantic_hash", sa.String(128), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("chunk_scope", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), server_default="indexed", nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.ForeignKeyConstraint(["knowledge_document_id"], ["knowledge.documents.id"], name="fk_knowledge_chunks_document", ondelete="CASCADE"),
        sa.UniqueConstraint("knowledge_document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
        sa.UniqueConstraint("published_chunk_id", name="uq_knowledge_chunks_published_chunk_id"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_chunks_document_id", "chunks", ["knowledge_document_id"], schema="knowledge")
    op.create_index("ix_knowledge_chunks_content_hash", "chunks", ["content_hash"], schema="knowledge")
    op.create_index("ix_knowledge_chunks_semantic_hash", "chunks", ["semantic_hash"], schema="knowledge")
    op.create_index("ix_knowledge_chunks_status", "chunks", ["status"], schema="knowledge")
    op.create_table(
        "metadata",
        sa.Column("id", UUID, nullable=False),
        sa.Column("knowledge_document_id", UUID, nullable=False),
        sa.Column("metadata_key", sa.String(128), nullable=False),
        sa.Column("metadata_value", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_metadata"),
        sa.ForeignKeyConstraint(["knowledge_document_id"], ["knowledge.documents.id"], name="fk_knowledge_metadata_document", ondelete="CASCADE"),
        sa.UniqueConstraint("knowledge_document_id", "metadata_key", name="uq_knowledge_metadata_document_key"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_metadata_document_id", "metadata", ["knowledge_document_id"], schema="knowledge")
    op.create_index("ix_knowledge_metadata_key", "metadata", ["metadata_key"], schema="knowledge")


def downgrade() -> None:
    op.drop_index("ix_knowledge_metadata_key", table_name="metadata", schema="knowledge")
    op.drop_index("ix_knowledge_metadata_document_id", table_name="metadata", schema="knowledge")
    op.drop_table("metadata", schema="knowledge")
    op.drop_index("ix_knowledge_chunks_status", table_name="chunks", schema="knowledge")
    op.drop_index("ix_knowledge_chunks_semantic_hash", table_name="chunks", schema="knowledge")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="chunks", schema="knowledge")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="chunks", schema="knowledge")
    op.drop_table("chunks", schema="knowledge")
    op.drop_index("ix_knowledge_documents_status", table_name="documents", schema="knowledge")
    op.drop_index("ix_knowledge_documents_publication_id", table_name="documents", schema="knowledge")
    op.drop_index("ix_knowledge_documents_artifact_id", table_name="documents", schema="knowledge")
    op.drop_table("documents", schema="knowledge")
