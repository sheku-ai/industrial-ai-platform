"""consolidate scheduler state into the runtime worker registry

Revision ID: 20260625_272a
Revises: 20260623_262a1
Create Date: 2026-06-25
"""

from alembic import op


revision = "20260625_272a"
down_revision = "20260623_262a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO runtime.workers (
            id,
            worker_key,
            instance_id,
            worker_type,
            desired_state,
            observed_state,
            capabilities,
            queue_keys,
            workload_classes,
            started_at,
            heartbeat_at,
            last_seen_at,
            metadata,
            metrics,
            last_error_code,
            last_error_message,
            created_at,
            updated_at
        )
        SELECT
            (
                substr(md5('legacy-scheduler-worker:' || legacy.id), 1, 8) || '-' ||
                substr(md5('legacy-scheduler-worker:' || legacy.id), 9, 4) || '-' ||
                substr(md5('legacy-scheduler-worker:' || legacy.id), 13, 4) || '-' ||
                substr(md5('legacy-scheduler-worker:' || legacy.id), 17, 4) || '-' ||
                substr(md5('legacy-scheduler-worker:' || legacy.id), 21, 12)
            )::uuid,
            legacy.id,
            left('legacy-scheduler:' || legacy.id || ':' || legacy.instance_id, 255),
            'runtime.scheduler',
            'active',
            'offline',
            '[
                "control_plane.schedule.dispatch",
                "control_plane.schedule.evaluation",
                "control_plane.schedule.runtime_sync"
            ]'::jsonb,
            '[]'::jsonb,
            '[]'::jsonb,
            legacy.started_at,
            legacy.heartbeat_at,
            legacy.heartbeat_at,
            jsonb_build_object(
                'legacy_source', 'control_plane.scheduler_workers',
                'legacy_instance_id', legacy.instance_id,
                'migration_revision', '20260625_272a'
            ),
            jsonb_strip_nulls(jsonb_build_object(
                'last_cycle_started_at', legacy.last_cycle_started_at,
                'last_cycle_completed_at', legacy.last_cycle_completed_at,
                'last_success_at', legacy.last_success_at,
                'last_error_at', legacy.last_error_at,
                'cycles_completed', legacy.cycles_completed,
                'organizations_processed', legacy.organizations_processed,
                'runs_created', legacy.runs_created
            )),
            legacy.last_error_type,
            left(legacy.last_error_message, 2000),
            legacy.started_at,
            legacy.updated_at
        FROM control_plane.scheduler_workers AS legacy
        ON CONFLICT (worker_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM runtime.workers
        WHERE metadata->>'migration_revision' = '20260625_272a'
          AND metadata->>'legacy_source' = 'control_plane.scheduler_workers'
        """
    )
