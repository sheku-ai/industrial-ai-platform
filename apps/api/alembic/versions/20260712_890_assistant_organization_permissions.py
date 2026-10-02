"""grant assistant permissions to governed organization administrators

Revision ID: 20260712_890
Revises: 20260712_880
Create Date: 2026-07-12 00:10:00.000000
"""

from alembic import op

revision = "20260712_890"
down_revision = "20260712_880"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO security.role_permissions (id, role_id, permission_id, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), rp.role_id, target.id, now(), now()
        FROM security.role_permissions rp
        JOIN security.permissions source ON source.id = rp.permission_id
        CROSS JOIN security.permissions target
        WHERE target.resource = 'platform.assistants'
          AND target.action = CASE WHEN source.action = 'administer' THEN 'administer' ELSE 'read' END
          AND source.resource = 'reference_tenant'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM security.role_permissions rp
        USING security.permissions target
        WHERE rp.permission_id = target.id
          AND target.resource = 'platform.assistants'
          AND EXISTS (
              SELECT 1
              FROM security.role_permissions source_rp
              JOIN security.permissions source ON source.id = source_rp.permission_id
              WHERE source_rp.role_id = rp.role_id
                AND source.resource = 'reference_tenant'
                AND source.action = target.action
          )
        """
    )
