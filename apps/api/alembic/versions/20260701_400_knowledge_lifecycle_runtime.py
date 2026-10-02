"""knowledge lifecycle runtime

Revision ID: 20260701_400
Revises: 20260701_390
Create Date: 2026-07-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260701_400"
down_revision: Union[str, None] = "20260701_390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "lifecycle_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("lifecycle_session_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=True),
        sa.Column("publication_id", sa.String(255), nullable=True),
        sa.Column("document_id", sa.String(128), nullable=True),
        sa.Column("decision", sa.String(32), nullable=True),
        sa.Column("documents_scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("documents_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("documents_invalidated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("documents_deleted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_deleted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicates_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("orphan_chunks_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stale_documents_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("obsolete_publications_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_lifecycle_runs"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_lifecycle_runs_operation", "lifecycle_runs", ["operation"], schema="knowledge")
    op.create_index("ix_knowledge_lifecycle_runs_status", "lifecycle_runs", ["status"], schema="knowledge")
    op.create_index("ix_knowledge_lifecycle_runs_artifact_id", "lifecycle_runs", ["artifact_id"], schema="knowledge")
    op.create_index("ix_knowledge_lifecycle_runs_publication_id", "lifecycle_runs", ["publication_id"], schema="knowledge")

    op.create_table(
        "index_health_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("indexed_documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_chunks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stale_documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("orphan_chunks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_chunks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending_updates", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending_reindex", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_incremental", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_reindex", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rebuild_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("statistics", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_index_health_snapshots"),
        schema="knowledge",
    )
    op.create_index("ix_knowledge_index_health_snapshots_created_at", "index_health_snapshots", ["created_at"], schema="knowledge")


def downgrade() -> None:
    op.drop_index("ix_knowledge_index_health_snapshots_created_at", table_name="index_health_snapshots", schema="knowledge")
    op.drop_table("index_health_snapshots", schema="knowledge")
    op.drop_index("ix_knowledge_lifecycle_runs_publication_id", table_name="lifecycle_runs", schema="knowledge")
    op.drop_index("ix_knowledge_lifecycle_runs_artifact_id", table_name="lifecycle_runs", schema="knowledge")
    op.drop_index("ix_knowledge_lifecycle_runs_status", table_name="lifecycle_runs", schema="knowledge")
    op.drop_index("ix_knowledge_lifecycle_runs_operation", table_name="lifecycle_runs", schema="knowledge")
    op.drop_table("lifecycle_runs", schema="knowledge")
