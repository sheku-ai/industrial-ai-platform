from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260622_2506b3"
down_revision = "20260621_2506a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("execution_class", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("configuration_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id", "execution_id"], ["runtime.executions.organization_id", "runtime.executions.id"], name="fk_documents_segment_plans_execution", ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "execution_id", name="uq_documents_segment_plans_execution"),
        sa.CheckConstraint("status IN ('planned','processing','completed','failed','cancelled')", name="ck_documents_segment_plans_status"),
        sa.CheckConstraint("segment_count > 0", name="ck_documents_segment_plans_segment_count"),
        schema="documents",
    )
    op.create_index("ix_documents_segment_plans_status", "segment_plans", ["organization_id", "status", "created_at"], schema="documents")
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("segment_key", sa.String(length=128), nullable=False),
        sa.Column("range_start", sa.BigInteger(), nullable=False),
        sa.Column("range_end_exclusive", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum_sha256", sa.String(length=64)),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["documents.segment_plans.id"], name="fk_documents_segments_plan", ondelete="CASCADE"),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_documents_segments_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_documents_segments_ordinal"),
        sa.CheckConstraint("range_start >= 0", name="ck_documents_segments_range_start"),
        sa.CheckConstraint("range_end_exclusive > range_start", name="ck_documents_segments_range"),
        sa.CheckConstraint("status IN ('pending','processing','completed','failed','cancelled')", name="ck_documents_segments_status"),
        schema="documents",
    )
    op.create_index("ix_documents_segments_status", "segments", ["plan_id", "status", "ordinal"], schema="documents")


def downgrade() -> None:
    op.drop_index("ix_documents_segments_status", table_name="segments", schema="documents")
    op.drop_table("segments", schema="documents")
    op.drop_index("ix_documents_segment_plans_status", table_name="segment_plans", schema="documents")
    op.drop_table("segment_plans", schema="documents")
