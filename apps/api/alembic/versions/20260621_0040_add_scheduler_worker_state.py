"""add scheduler worker state

Revision ID: 20260621_0040
Revises: 20260621_0030
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260621_0040"
down_revision: str | Sequence[str] | None = "20260621_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_workers",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_cycle_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_type", sa.String(length=255), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("cycles_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("organizations_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("runs_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="control_plane",
    )
    op.create_index(
        "ix_control_plane_scheduler_workers_heartbeat",
        "scheduler_workers",
        ["heartbeat_at"],
        unique=False,
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_control_plane_scheduler_workers_heartbeat",
        table_name="scheduler_workers",
        schema="control_plane",
    )
    op.drop_table("scheduler_workers", schema="control_plane")
