from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260623_261a"
down_revision = "20260623_25113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=True),
        sa.Column("configuration_type", sa.String(length=64), nullable=False),
        sa.Column("configuration_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "length(btrim(configuration_key)) > 0",
            name="ck_runtime_configurations_key_not_blank",
        ),
        sa.CheckConstraint(
            "(scope_type = 'platform' AND organization_id IS NULL AND scope_key IS NULL) OR "
            "(scope_type = 'organization' AND organization_id IS NOT NULL AND scope_key IS NULL) OR "
            "(scope_type IN ('worker','workload_class') AND scope_key IS NOT NULL AND length(btrim(scope_key)) > 0)",
            name="ck_runtime_configurations_scope_shape",
        ),
        sa.CheckConstraint(
            "scope_type IN ('platform','organization','worker','workload_class')",
            name="ck_runtime_configurations_scope_type",
        ),
        sa.CheckConstraint(
            "length(btrim(configuration_type)) > 0",
            name="ck_runtime_configurations_type_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_runtime_configurations_organization",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_configurations"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_runtime_configurations_tenant_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scope_type",
            "scope_key",
            "configuration_type",
            "configuration_key",
            name="uq_runtime_configurations_scope_key",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_configurations_resolution",
        "configurations",
        [
            "configuration_type",
            "configuration_key",
            "scope_type",
            "organization_id",
            "scope_key",
        ],
        schema="runtime",
    )
    op.create_index(
        "uq_runtime_configurations_platform_scope",
        "configurations",
        ["configuration_type", "configuration_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("scope_type = 'platform'"),
    )
    op.create_index(
        "uq_runtime_configurations_organization_scope",
        "configurations",
        ["organization_id", "configuration_type", "configuration_key"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("scope_type = 'organization'"),
    )
    op.create_index(
        "uq_runtime_configurations_named_scope",
        "configurations",
        [
            "organization_id",
            "scope_type",
            "scope_key",
            "configuration_type",
            "configuration_key",
        ],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("scope_type IN ('worker','workload_class')"),
    )

    op.create_table(
        "configuration_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("configuration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_runtime_configuration_revisions_effective_window",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_runtime_configuration_revisions_payload_object",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_runtime_configuration_revisions_positive_revision",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_runtime_configuration_revisions_positive_schema_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','superseded','disabled')",
            name="ck_runtime_configuration_revisions_status",
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["runtime.configurations.id"],
            name="fk_runtime_configuration_revisions_configuration",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "configuration_id"],
            ["runtime.configurations.organization_id", "runtime.configurations.id"],
            name="fk_runtime_configuration_revisions_tenant_configuration",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_configuration_revisions"),
        sa.UniqueConstraint(
            "configuration_id",
            "id",
            name="uq_runtime_configuration_revisions_configuration_id",
        ),
        sa.UniqueConstraint(
            "configuration_id",
            "revision",
            name="uq_runtime_configuration_revisions_number",
        ),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_configuration_revisions_effective",
        "configuration_revisions",
        ["configuration_id", "status", "effective_from", "effective_until"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_configuration_revisions_schema",
        "configuration_revisions",
        ["configuration_id", "schema_version"],
        schema="runtime",
    )
    op.create_index(
        "uq_runtime_configuration_revisions_active",
        "configuration_revisions",
        ["configuration_id"],
        unique=True,
        schema="runtime",
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_runtime_configuration_revisions_active",
        table_name="configuration_revisions",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_configuration_revisions_schema",
        table_name="configuration_revisions",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_configuration_revisions_effective",
        table_name="configuration_revisions",
        schema="runtime",
    )
    op.drop_table("configuration_revisions", schema="runtime")

    op.drop_index(
        "uq_runtime_configurations_named_scope",
        table_name="configurations",
        schema="runtime",
    )
    op.drop_index(
        "uq_runtime_configurations_organization_scope",
        table_name="configurations",
        schema="runtime",
    )
    op.drop_index(
        "uq_runtime_configurations_platform_scope",
        table_name="configurations",
        schema="runtime",
    )
    op.drop_index(
        "ix_runtime_configurations_resolution",
        table_name="configurations",
        schema="runtime",
    )
    op.drop_table("configurations", schema="runtime")
