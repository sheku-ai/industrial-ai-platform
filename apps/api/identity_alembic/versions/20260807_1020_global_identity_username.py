"""add governed username to local identities

Revision ID: 20260807_1020
Revises: 20260727_1010
Create Date: 2026-08-07 00:00:00+00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260807_1020"
down_revision = "20260727_1010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("username", sa.String(length=128), nullable=True),
        schema="identity",
    )
    op.execute(
        """
        WITH candidates AS (
            SELECT id,
                   btrim(regexp_replace(
                       lower(split_part(email_normalized, '@', 1)),
                       '[^a-z0-9._-]+', '-', 'g'
                   ), '._-') AS base
            FROM identity.users
        ), ranked AS (
            SELECT id,
                   left(CASE WHEN base = '' THEN 'user' ELSE base END, 96) AS base,
                   row_number() OVER (
                       PARTITION BY left(CASE WHEN base = '' THEN 'user' ELSE base END, 96)
                       ORDER BY id
                   ) AS occurrence
            FROM candidates
        )
        UPDATE identity.users AS users
        SET username = ranked.base ||
            CASE WHEN ranked.occurrence = 1 THEN '' ELSE '-' || ranked.occurrence::text END
        FROM ranked
        WHERE users.id = ranked.id
        """
    )
    op.alter_column("users", "username", nullable=False, schema="identity")
    op.create_index(
        "ix_identity_users_username",
        "users",
        ["username"],
        unique=True,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("ix_identity_users_username", table_name="users", schema="identity")
    op.drop_column("users", "username", schema="identity")
