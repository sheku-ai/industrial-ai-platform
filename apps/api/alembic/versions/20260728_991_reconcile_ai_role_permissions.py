"""reconcile AI configuration permissions for protected organization administrators

Revision ID: 20260728_991
Revises: 20260728_990
Create Date: 2026-07-28 00:00:01.000000
"""

from alembic import op

revision = "20260728_991"
down_revision = "20260728_990"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO security.role_permissions (
            id, role_id, permission_id, created_at, updated_at
        )
        SELECT DISTINCT
            gen_random_uuid(),
            source_link.role_id,
            target_permission.id,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM security.role_permissions source_link
        JOIN security.permissions source_permission
          ON source_permission.id = source_link.permission_id
        JOIN security.roles role
          ON role.id = source_link.role_id
        CROSS JOIN security.permissions target_permission
        WHERE source_permission.resource = 'reference_tenant'
          AND source_permission.action = 'administer'
          AND role.organization_id IS NOT NULL
          AND role.status = 'active'
          AND (
              role.is_system
              OR role.config @> '{"protected": true}'::jsonb
              OR role.config @> '{"baseline_required": true}'::jsonb
              OR role.config @> '{"reference_tenant": true}'::jsonb
              OR role.config @> '{"canonical_product_reference": true}'::jsonb
              OR role.config ->> 'managed_by' = 'platform'
          )
          AND (target_permission.resource, target_permission.action) IN (
              ('ai.configuration', 'read'),
              ('ai.providers', 'administer'),
              ('ai.models', 'administer'),
              ('ai.validation', 'execute')
          )
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """Preserve grants because role_permissions has no authoritative provenance.

    A link inserted by this revision is indistinguishable from the same link
    subsequently retained or managed by an administrator. Deleting links by
    permission key and role eligibility could therefore revoke legitimate
    access. The safe downgrade is intentionally non-destructive.
    """
