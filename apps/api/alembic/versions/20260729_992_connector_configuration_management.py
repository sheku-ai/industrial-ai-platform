"""Add explicit connector credential reference storage.

Revision ID: 20260729_992
Revises: 20260728_991
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_992"
down_revision: str | None = "20260728_991"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connectors",
        sa.Column("credential_resolver_type", sa.String(length=64), nullable=True),
        schema="connectors",
    )
    op.add_column(
        "connectors",
        sa.Column("credential_reference", sa.String(length=1024), nullable=True),
        schema="connectors",
    )
    op.create_check_constraint(
        "ck_connectors_connectors_credential_reference_pair",
        "connectors",
        "(credential_resolver_type IS NULL AND credential_reference IS NULL) OR "
        "(credential_resolver_type IS NOT NULL AND credential_reference IS NOT NULL)",
        schema="connectors",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_connectors_connectors_credential_reference_pair",
        "connectors",
        schema="connectors",
        type_="check",
    )
    op.drop_column("connectors", "credential_reference", schema="connectors")
    op.drop_column("connectors", "credential_resolver_type", schema="connectors")
