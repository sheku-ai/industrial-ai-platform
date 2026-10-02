"""align Alembic schema with SQLAlchemy metadata

Revision ID: 20260620_2350
Revises: 20260620_2302
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260620_2350"
down_revision: str | Sequence[str] | None = "20260620_2302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical databases can legitimately differ here because earlier model
    # definitions created either a unique constraint, a convention-named index,
    # or both. Normalize all supported predecessor states to the canonical index.
    op.execute("DROP INDEX IF EXISTS core.ix_organizations_slug")
    op.execute(
        "ALTER TABLE core.organizations "
        "DROP CONSTRAINT IF EXISTS uq_organizations_slug"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_core_organizations_slug "
        "ON core.organizations (slug)"
    )

    op.alter_column(
        "indexing_jobs",
        "collection_id",
        schema="documents",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "indexing_jobs",
        "collection_id",
        schema="documents",
        existing_type=sa.UUID(),
        nullable=False,
    )

    op.execute("DROP INDEX IF EXISTS core.ix_core_organizations_slug")
    op.execute(
        "ALTER TABLE core.organizations "
        "DROP CONSTRAINT IF EXISTS uq_organizations_slug"
    )
    op.execute("DROP INDEX IF EXISTS core.ix_organizations_slug")
    op.execute(
        "ALTER TABLE core.organizations "
        "ADD CONSTRAINT uq_organizations_slug UNIQUE (slug)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_slug "
        "ON core.organizations (slug)"
    )
