"""platform foundation baseline

Revision ID: 0001_platform_foundation
Revises: 20260618_0001
Create Date: 2026-06-18
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0001_platform_foundation"
down_revision: Union[str, None] = "20260618_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)")
