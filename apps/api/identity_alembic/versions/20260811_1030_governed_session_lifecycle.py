"""add governed local session lifecycle

Revision ID: 20260811_1030
Revises: 20260807_1020
Create Date: 2026-08-11 00:00:00+00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260811_1030"
down_revision = "20260807_1020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("absolute_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_sessions", sa.Integer(), nullable=False),
        sa.Column("activity_write_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("remember_me_enabled", sa.Boolean(), nullable=False),
        sa.Column("remember_idle_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("remember_absolute_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'platform'", name="session_policies_platform_scope"),
        sa.CheckConstraint("status = 'active'", name="session_policies_active_status"),
        sa.CheckConstraint("version > 0", name="session_policies_positive_version"),
        sa.CheckConstraint("idle_timeout_seconds BETWEEN 60 AND 86400", name="session_policies_idle_range"),
        sa.CheckConstraint("absolute_timeout_seconds BETWEEN 300 AND 2592000", name="session_policies_absolute_range"),
        sa.CheckConstraint("max_concurrent_sessions BETWEEN 1 AND 100", name="session_policies_concurrency_range"),
        sa.CheckConstraint("activity_write_interval_seconds BETWEEN 30 AND 3600", name="session_policies_touch_range"),
        sa.CheckConstraint(
            "activity_write_interval_seconds < idle_timeout_seconds",
            name="session_policies_touch_before_idle",
        ),
        sa.CheckConstraint(
            "activity_write_interval_seconds < remember_idle_timeout_seconds",
            name="session_policies_touch_before_remember_idle",
        ),
        sa.CheckConstraint(
            "remember_idle_timeout_seconds BETWEEN 60 AND 604800", name="session_policies_remember_idle_range"
        ),
        sa.CheckConstraint(
            "remember_absolute_timeout_seconds BETWEEN 300 AND 31536000",
            name="session_policies_remember_absolute_range",
        ),
        sa.CheckConstraint("retention_days BETWEEN 1 AND 3650", name="session_policies_retention_range"),
        sa.CheckConstraint(
            "idle_timeout_seconds <= absolute_timeout_seconds", name="session_policies_standard_coherent"
        ),
        sa.CheckConstraint(
            "remember_idle_timeout_seconds <= remember_absolute_timeout_seconds",
            name="session_policies_remember_coherent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", name="uq_identity_session_policy_scope"),
        schema="identity",
    )
    op.execute(
        """INSERT INTO identity.session_policies
        (id, scope, status, version, idle_timeout_seconds, absolute_timeout_seconds,
         max_concurrent_sessions, activity_write_interval_seconds, remember_me_enabled,
         remember_idle_timeout_seconds, remember_absolute_timeout_seconds, retention_days)
        VALUES (gen_random_uuid(), 'platform', 'active', 1, 1800, 28800, 3, 300, false, 86400, 604800, 90)
        ON CONFLICT (scope) DO NOTHING"""
    )
    op.drop_index("ix_identity_auth_sessions_user_active", table_name="auth_sessions", schema="identity")
    op.alter_column("auth_sessions", "last_seen_at", new_column_name="last_activity_at", schema="identity")
    op.alter_column("auth_sessions", "expires_at", new_column_name="absolute_expires_at", schema="identity")
    op.add_column(
        "auth_sessions", sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=True), schema="identity"
    )
    op.add_column(
        "auth_sessions",
        sa.Column("idle_timeout_seconds", sa.Integer(), server_default="1800", nullable=False),
        schema="identity",
    )
    op.add_column(
        "auth_sessions",
        sa.Column("policy_version", sa.Integer(), server_default="1", nullable=False),
        schema="identity",
    )
    op.add_column(
        "auth_sessions",
        sa.Column("remember_me", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="identity",
    )
    op.add_column("auth_sessions", sa.Column("client_ip", sa.String(length=128), nullable=True), schema="identity")
    op.add_column("auth_sessions", sa.Column("user_agent", sa.String(length=512), nullable=True), schema="identity")
    op.add_column(
        "auth_sessions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="identity",
    )
    op.execute("""UPDATE identity.auth_sessions
        SET idle_expires_at = LEAST(last_activity_at + interval '30 minutes', absolute_expires_at),
            client_ip = NULLIF(metadata->>'origin', ''),
            user_agent = NULLIF(metadata->>'user_agent', '')""")
    op.alter_column("auth_sessions", "idle_expires_at", nullable=False, schema="identity")
    op.alter_column("auth_sessions", "idle_timeout_seconds", server_default=None, schema="identity")
    op.alter_column("auth_sessions", "policy_version", server_default=None, schema="identity")
    op.create_index(
        "ix_identity_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "revoked_at", "idle_expires_at", "absolute_expires_at"],
        schema="identity",
    )
    op.add_column(
        "authentication_events",
        sa.Column("actor_reference", sa.String(length=255), nullable=True),
        schema="identity",
    )
    op.add_column(
        "authentication_events",
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        schema="identity",
    )
    op.alter_column("authentication_events", "metadata", server_default=None, schema="identity")


def downgrade() -> None:
    op.drop_column("authentication_events", "metadata", schema="identity")
    op.drop_column("authentication_events", "actor_reference", schema="identity")
    op.drop_index("ix_identity_auth_sessions_user_active", table_name="auth_sessions", schema="identity")
    op.drop_column("auth_sessions", "updated_at", schema="identity")
    op.drop_column("auth_sessions", "user_agent", schema="identity")
    op.drop_column("auth_sessions", "client_ip", schema="identity")
    op.drop_column("auth_sessions", "remember_me", schema="identity")
    op.drop_column("auth_sessions", "idle_expires_at", schema="identity")
    op.drop_column("auth_sessions", "policy_version", schema="identity")
    op.drop_column("auth_sessions", "idle_timeout_seconds", schema="identity")
    op.alter_column("auth_sessions", "absolute_expires_at", new_column_name="expires_at", schema="identity")
    op.alter_column("auth_sessions", "last_activity_at", new_column_name="last_seen_at", schema="identity")
    op.create_index(
        "ix_identity_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "revoked_at", "expires_at"],
        schema="identity",
    )
    op.drop_table("session_policies", schema="identity")
