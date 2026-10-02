"""align role permission timestamp defaults

Revision ID: 20260819_1000
Revises: 20260816_999
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_1000"
down_revision: str | Sequence[str] | None = "20260816_999"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "role_permissions",
        "created_at",
        schema="security",
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "role_permissions",
        "updated_at",
        schema="security",
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "role_permissions",
        "updated_at",
        schema="security",
        server_default=None,
    )
    op.alter_column(
        "role_permissions",
        "created_at",
        schema="security",
        server_default=None,
    )
