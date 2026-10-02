"""add immutable artifact publications

Revision ID: 20260619_2180
Revises: 20260619_2160
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260619_2180"
down_revision = "20260619_2160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publication_number", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("publication_number > 0", name="ck_runtime_artifact_publications_number"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_artifact_publications_size"),
        sa.CheckConstraint("checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_runtime_artifact_publications_checksum"),
        sa.CheckConstraint(
            "status IN ('reserved','publishing','published','verified','missing','checksum_conflict','reconciliation_required','failed','retained','deleted')",
            name="ck_runtime_artifact_publications_status",
        ),
        sa.CheckConstraint("verified_at IS NULL OR published_at IS NOT NULL", name="ck_runtime_artifact_publications_verified_after_publish"),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["runtime.execution_artifacts.id"],
            name="fk_runtime_artifact_publications_artifact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "execution_id", "attempt_id"],
            ["runtime.execution_attempts.organization_id", "runtime.execution_attempts.execution_id", "runtime.execution_attempts.id"],
            name="fk_runtime_artifact_publications_attempt",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_publications"),
        sa.UniqueConstraint("artifact_id", "publication_number", name="uq_runtime_artifact_publications_number"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_artifact_publications_status",
        "artifact_publications",
        ["organization_id", "execution_id", "status"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_artifact_publications_artifact",
        "artifact_publications",
        ["organization_id", "artifact_id", "created_at"],
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_artifact_publications_artifact", table_name="artifact_publications", schema="runtime")
    op.drop_index("ix_runtime_artifact_publications_status", table_name="artifact_publications", schema="runtime")
    op.drop_table("artifact_publications", schema="runtime")
