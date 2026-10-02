"""Add the governed organization structure aggregate.

Revision ID: 20260729_993
Revises: 20260729_992
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_993"
down_revision: str | None = "20260729_992"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_node_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("allows_children", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "allowed_child_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "presentation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_for_new", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("edition", sa.String(length=32), server_default="community", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_core_organization_node_types_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_child_types) = 'array'",
            name="ck_core_organization_node_types_allowed_children",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(presentation_metadata) = 'object'",
            name="ck_core_organization_node_types_presentation",
        ),
        sa.CheckConstraint(
            "edition IN ('community', 'enterprise')",
            name="ck_core_organization_node_types_edition",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_organization_node_types_code"),
        schema="core",
    )
    op.create_index(
        "ix_core_organization_node_types_catalog",
        "organization_node_types",
        ["status", "display_order"],
        schema="core",
    )

    op.create_table(
        "organization_structure_aggregates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_mutation_key", sa.String(length=64), nullable=True),
        sa.Column("last_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_core_organization_structure_revision",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_organization_structure_organization",
        ),
        sa.PrimaryKeyConstraint("organization_id"),
        schema="core",
    )
    op.execute(
        """
        INSERT INTO core.organization_structure_aggregates (
            organization_id,
            revision,
            created_at,
            updated_at,
            created_by,
            updated_by
        )
        SELECT
            organization.id,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            'migration:20260729_993',
            'migration:20260729_993'
        FROM core.organizations organization
        ON CONFLICT (organization_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.initialize_organization_structure_aggregate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO core.organization_structure_aggregates (
                organization_id,
                revision,
                created_at,
                updated_at,
                created_by,
                updated_by
            )
            VALUES (
                NEW.id,
                0,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                COALESCE(NEW.created_by, 'database:organization_insert'),
                COALESCE(NEW.created_by, 'database:organization_insert')
            )
            ON CONFLICT (organization_id) DO NOTHING;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_initialize_organization_structure_aggregate
        AFTER INSERT ON core.organizations
        FOR EACH ROW
        EXECUTE FUNCTION core.initialize_organization_structure_aggregate()
        """
    )

    op.execute(
        """
        INSERT INTO core.organization_node_types (
            id,
            code,
            name,
            description,
            status,
            allows_children,
            allowed_child_types,
            presentation_metadata,
            display_order,
            available_for_new,
            edition,
            created_at,
            updated_at,
            created_by,
            updated_by
        )
        VALUES
            (
                gen_random_uuid(),
                'structure_root',
                'Structure root',
                'Generic root for an organization structure.',
                'active',
                TRUE,
                '[]'::jsonb,
                '{"shape": "root"}'::jsonb,
                10,
                TRUE,
                'community',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                'migration:20260729_993',
                'migration:20260729_993'
            ),
            (
                gen_random_uuid(),
                'structure_group',
                'Structure group',
                'Generic grouping node within an organization structure.',
                'active',
                TRUE,
                '[]'::jsonb,
                '{"shape": "group"}'::jsonb,
                20,
                TRUE,
                'community',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                'migration:20260729_993',
                'migration:20260729_993'
            ),
            (
                gen_random_uuid(),
                'structure_node',
                'Structure node',
                'Generic terminal node within an organization structure.',
                'active',
                FALSE,
                '[]'::jsonb,
                '{"shape": "node"}'::jsonb,
                30,
                TRUE,
                'community',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                'migration:20260729_993',
                'migration:20260729_993'
            )
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_initialize_organization_structure_aggregate "
        "ON core.organizations"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS core.initialize_organization_structure_aggregate()"
    )
    op.drop_table("organization_structure_aggregates", schema="core")
    op.drop_index(
        "ix_core_organization_node_types_catalog",
        table_name="organization_node_types",
        schema="core",
    )
    op.drop_table("organization_node_types", schema="core")
