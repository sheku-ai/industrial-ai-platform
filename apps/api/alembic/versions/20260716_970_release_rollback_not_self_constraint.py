"""normalize release rollback self-reference constraint

Revision ID: 20260716_970
Revises: 20260715_960
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op

revision = "20260716_970"
down_revision = "20260715_960"
branch_labels = None
depends_on = None

SCHEMA = "runtime"
TABLE = "release_rollback_targets"
CONSTRAINT = "ck_runtime_release_rollback_not_self"
LEGACY_CONSTRAINT = "ck_release_rollback_targets_ck_runtime_release_rollback_not_self"
EXPRESSION = (
    "release_id IS NULL OR rollback_target_release_id IS NULL "
    "OR release_id <> rollback_target_release_id"
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM {SCHEMA}.{TABLE}
                WHERE release_id = rollback_target_release_id
            ) THEN
                RAISE EXCEPTION
                    'cannot add {CONSTRAINT}: self-referencing rollback targets exist';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{LEGACY_CONSTRAINT}'
                  AND conrelid = '{SCHEMA}.{TABLE}'::regclass
            ) THEN
                ALTER TABLE {SCHEMA}.{TABLE}
                    DROP CONSTRAINT {LEGACY_CONSTRAINT};
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{CONSTRAINT}'
                  AND conrelid = '{SCHEMA}.{TABLE}'::regclass
            ) THEN
                ALTER TABLE {SCHEMA}.{TABLE}
                    ADD CONSTRAINT {CONSTRAINT} CHECK ({EXPRESSION});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.{TABLE}
            DROP CONSTRAINT IF EXISTS {CONSTRAINT};
        ALTER TABLE {SCHEMA}.{TABLE}
            ADD CONSTRAINT {LEGACY_CONSTRAINT} CHECK ({EXPRESSION});
        """
    )
