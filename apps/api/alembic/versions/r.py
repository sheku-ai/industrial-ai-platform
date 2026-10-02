"""add ingestion pipeline profiles"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260619_2130"
down_revision = "20260619_1906"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_pipeline_profiles",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("deployment_edition", sa.String(32), server_default="community", nullable=False),
        sa.Column("default_adapter_key", sa.String(255), nullable=True),
        sa.Column("adapter_policies", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("adapter_versions", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("adapter_settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", "revision", name="uq_ingestion_pipeline_profiles_org_code_revision"),
        schema="documents",
    )
    op.create_index(
        "ix_ingestion_pipeline_profiles_org_enabled",
        "ingestion_pipeline_profiles",
        ["organization_id", "enabled"],
        schema="documents",
    )


def downgrade():
    op.drop_index(
        "ix_ingestion_pipeline_profiles_org_enabled",
        table_name="ingestion_pipeline_profiles",
        schema="documents",
    )
    op.drop_table("ingestion_pipeline_profiles", schema="documents")
