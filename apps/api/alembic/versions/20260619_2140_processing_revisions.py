"""add processing revisions

Revision ID: 20260619_2140
Revises: 20260619_2130
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260619_2140"
down_revision: str | None = "20260619_2130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_revisions",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_profile_revision", sa.String(length=128), nullable=False),
        sa.Column("adapter_key", sa.String(length=128), nullable=False),
        sa.Column("adapter_version", sa.String(length=128), nullable=False),
        sa.Column("configuration_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="processing"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_unit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"]),
        sa.ForeignKeyConstraint(["runtime_execution_id"], ["runtime.executions.id"]),
        sa.ForeignKeyConstraint(["runtime_attempt_id"], ["runtime.execution_attempts.id"]),
        sa.ForeignKeyConstraint(["pipeline_profile_id"], ["documents.ingestion_pipeline_profiles.id"]),
        sa.ForeignKeyConstraint(["manifest_artifact_id"], ["runtime.execution_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "runtime_execution_id", "runtime_attempt_id", name="uq_processing_revisions_runtime_attempt"),
        schema="documents",
    )
    op.create_index("ix_processing_revisions_document_version_id", "processing_revisions", ["document_version_id"], schema="documents")
    op.create_index("ix_processing_revisions_runtime_execution_id", "processing_revisions", ["runtime_execution_id"], schema="documents")
    op.create_index("ix_processing_revisions_status", "processing_revisions", ["status"], schema="documents")


def downgrade() -> None:
    op.drop_index("ix_processing_revisions_status", table_name="processing_revisions", schema="documents")
    op.drop_index("ix_processing_revisions_runtime_execution_id", table_name="processing_revisions", schema="documents")
    op.drop_index("ix_processing_revisions_document_version_id", table_name="processing_revisions", schema="documents")
    op.drop_table("processing_revisions", schema="documents")
