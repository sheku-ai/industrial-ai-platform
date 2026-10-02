"""create independent identity authentication core

Revision ID: 20260725_1000
Revises:
Create Date: 2026-07-25 10:00:00+00:00
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260725_1000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("email_display", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_users_users_status"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        schema="identity",
    )
    op.create_index(
        "ix_identity_users_email_normalized",
        "users",
        ["email_normalized"],
        unique=True,
        schema="identity",
    )

    op.create_table(
        "password_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_password_credentials_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_password_credentials"),
        schema="identity",
    )

    op.create_table(
        "organization_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')",
            name="ck_organization_memberships_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_organization_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_memberships"),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            "role_id",
            name="uq_identity_membership_user_org_role",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_active_membership_user_org",
        "organization_memberships",
        ["user_id", "organization_id"],
        unique=True,
        schema="identity",
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        schema="identity",
    )
    op.create_index(
        "ix_identity_auth_sessions_token_hash",
        "auth_sessions",
        ["token_hash"],
        unique=True,
        schema="identity",
    )
    op.create_index(
        "ix_identity_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
        schema="identity",
    )

    op.create_table(
        "authentication_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("origin", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["identity.auth_sessions.id"],
            name="fk_authentication_events_session_id_auth_sessions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_authentication_events_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authentication_events"),
        schema="identity",
    )
    op.create_index(
        "ix_identity_auth_events_user_occurred",
        "authentication_events",
        ["user_id", "occurred_at"],
        unique=False,
        schema="identity",
    )
    op.create_index(
        "ix_identity_auth_events_email_occurred",
        "authentication_events",
        ["email_normalized", "occurred_at"],
        unique=False,
        schema="identity",
    )
    op.create_index(
        "ix_identity_auth_events_type_occurred",
        "authentication_events",
        ["event_type", "occurred_at"],
        unique=False,
        schema="identity",
    )

    op.create_table(
        "login_throttles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("origin", sa.String(length=128), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_login_throttles"),
        sa.UniqueConstraint(
            "email_normalized",
            "origin",
            name="uq_identity_login_throttle_account_origin",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_login_throttles_blocked_until",
        "login_throttles",
        ["blocked_until"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_identity_login_throttles_blocked_until",
        table_name="login_throttles",
        schema="identity",
    )
    op.drop_table("login_throttles", schema="identity")
    op.drop_index(
        "ix_identity_auth_events_type_occurred",
        table_name="authentication_events",
        schema="identity",
    )
    op.drop_index(
        "ix_identity_auth_events_email_occurred",
        table_name="authentication_events",
        schema="identity",
    )
    op.drop_index(
        "ix_identity_auth_events_user_occurred",
        table_name="authentication_events",
        schema="identity",
    )
    op.drop_table("authentication_events", schema="identity")
    op.drop_index(
        "ix_identity_auth_sessions_user_active",
        table_name="auth_sessions",
        schema="identity",
    )
    op.drop_index(
        "ix_identity_auth_sessions_token_hash",
        table_name="auth_sessions",
        schema="identity",
    )
    op.drop_table("auth_sessions", schema="identity")
    op.drop_index(
        "ix_identity_active_membership_user_org",
        table_name="organization_memberships",
        schema="identity",
    )
    op.drop_table("organization_memberships", schema="identity")
    op.drop_table("password_credentials", schema="identity")
    op.drop_index(
        "ix_identity_users_email_normalized",
        table_name="users",
        schema="identity",
    )
    op.drop_table("users", schema="identity")
    op.execute("DROP SCHEMA IF EXISTS identity")
