"""merge concurrent sprint 21 heads

Revision ID: 20260619_2150
Revises: 20260619_2130, 20260619_2140
"""

from collections.abc import Sequence

revision: str = "20260619_2150"
down_revision: tuple[str, str] = ("20260619_2130", "20260619_2140")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
