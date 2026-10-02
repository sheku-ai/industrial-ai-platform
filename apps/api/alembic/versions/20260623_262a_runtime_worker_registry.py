from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260623_262a"
down_revision = "20260623_261a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_key", sa.String(length=255), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=False),
        sa.Column("worker_type", sa.String(length=64), nullable=False),
        sa.Column("runtime_version", sa.String(length=64), nullable=True),
        sa.Column("desired_state", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("observed_state", sa.String(length=32), server_default="starting", nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("queue_keys", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("workload_classes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("active_configuration_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(worker_key)) > 0", name="ck_runtime_workers_worker_key_not_blank"),
        sa.CheckConstraint("length(btrim(instance_id)) > 0", name="ck_runtime_workers_instance_id_not_blank"),
        sa.CheckConstraint("length(btrim(worker_type)) > 0", name="ck_runtime_workers_worker_type_not_blank"),
        sa.CheckConstraint("desired_state IN ('active','paused','draining','disabled')", name="ck_runtime_workers_desired_state"),
        sa.CheckConstraint("observed_state IN ('starting','ready','busy','paused','draining','offline','failed')", name="ck_runtime_workers_observed_state"),
        sa.CheckConstraint("jsonb_typeof(capabilities) = 'array'", name="ck_runtime_workers_capabilities_array"),
        sa.CheckConstraint("jsonb_typeof(queue_keys) = 'array'", name="ck_runtime_workers_queue_keys_array"),
        sa.CheckConstraint("jsonb_typeof(workload_classes) = 'array'", name="ck_runtime_workers_workload_classes_array"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_runtime_workers_metadata_object"),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'object'", name="ck_runtime_workers_metrics_object"),
        sa.CheckConstraint("ready_at IS NULL OR ready_at >= started_at", name="ck_runtime_workers_ready_at"),
        sa.CheckConstraint("heartbeat_at IS NULL OR heartbeat_at >= started_at", name="ck_runtime_workers_heartbeat_at"),
        sa.CheckConstraint("last_seen_at IS NULL OR heartbeat_at IS NULL OR last_seen_at >= heartbeat_at", name="ck_runtime_workers_last_seen_at"),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_workers"),
        sa.UniqueConstraint("worker_key", name="uq_runtime_workers_worker_key"),
        sa.UniqueConstraint("instance_id", name="uq_runtime_workers_instance_id"),
        schema="runtime",
    )
    op.create_index("ix_runtime_workers_type_state", "workers", ["worker_type", "observed_state"], schema="runtime")
    op.create_index("ix_runtime_workers_heartbeat", "workers", ["observed_state", "heartbeat_at"], schema="runtime")
    op.create_index("ix_runtime_workers_desired_observed", "workers", ["desired_state", "observed_state"], schema="runtime")


def downgrade() -> None:
    op.drop_index("ix_runtime_workers_desired_observed", table_name="workers", schema="runtime")
    op.drop_index("ix_runtime_workers_heartbeat", table_name="workers", schema="runtime")
    op.drop_index("ix_runtime_workers_type_state", table_name="workers", schema="runtime")
    op.drop_table("workers", schema="runtime")
