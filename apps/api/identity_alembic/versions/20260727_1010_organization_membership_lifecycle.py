"""add organization membership removal lifecycle

Revision ID: 20260727_1010
Revises: 20260725_1000
Create Date: 2026-07-27 00:00:00+00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260727_1010"
down_revision = "20260725_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        schema="identity",
    )
    op.drop_constraint(
        "ck_organization_memberships_memberships_status",
        "organization_memberships",
        schema="identity",
        type_="check",
    )
    op.create_check_constraint(
        "memberships_status",
        "organization_memberships",
        "status IN ('active', 'suspended', 'removed')",
        schema="identity",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE identity.organization_memberships "
        "SET status = 'suspended', suspended_at = COALESCE(suspended_at, removed_at) "
        "WHERE status = 'removed'"
    )
    op.drop_constraint(
        "ck_organization_memberships_memberships_status",
        "organization_memberships",
        schema="identity",
        type_="check",
    )
    op.create_check_constraint(
        "memberships_status",
        "organization_memberships",
        "status IN ('active', 'suspended')",
        schema="identity",
    )
    op.drop_column("organization_memberships", "removed_at", schema="identity")
