"""register control plane permission capabilities

Revision ID: 20260621_0020
Revises: 20260621_0010
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260621_0020"
down_revision: str | Sequence[str] | None = "20260621_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = (
    ("control_plane.health", "read", "Read organization operational health snapshots"),
    ("control_plane.reconciliation", "read", "Preview organization artifact reconciliation"),
    ("control_plane.reconciliation", "administer", "Run organization artifact reconciliation"),
)


def upgrade() -> None:
    statement = sa.text(
        """
        INSERT INTO security.permissions (
            id, resource, action, description, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(),
            :resource,
            :action,
            :description,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (resource, action) DO UPDATE
        SET description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    connection = op.get_bind()
    for resource, action, description in PERMISSIONS:
        connection.execute(
            statement,
            {"resource": resource, "action": action, "description": description},
        )


def downgrade() -> None:
    statement = sa.text(
        "DELETE FROM security.permissions WHERE resource = :resource AND action = :action"
    )
    connection = op.get_bind()
    for resource, action, _description in PERMISSIONS:
        connection.execute(statement, {"resource": resource, "action": action})
