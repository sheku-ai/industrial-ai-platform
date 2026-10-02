from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.base import IdentityBase


class IdentityTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IdentityUser(IdentityTimestampMixin, IdentityBase):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="users_status"),
        Index("ix_identity_users_username", "username", unique=True),
        Index("ix_identity_users_email_normalized", "email_normalized", unique=True),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordCredential(IdentityTimestampMixin, IdentityBase):
    __tablename__ = "password_credentials"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrganizationMembership(IdentityTimestampMixin, IdentityBase):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'removed')", name="memberships_status"),
        UniqueConstraint(
            "user_id",
            "organization_id",
            "role_id",
            name="uq_identity_membership_user_org_role",
        ),
        Index(
            "ix_identity_active_membership_user_org",
            "user_id",
            "organization_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(IdentityBase):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_identity_auth_sessions_token_hash", "token_hash", unique=True),
        Index(
            "ix_identity_auth_sessions_user_active",
            "user_id",
            "revoked_at",
            "idle_expires_at",
            "absolute_expires_at",
        ),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class SessionPolicy(IdentityTimestampMixin, IdentityBase):
    __tablename__ = "session_policies"
    __table_args__ = (
        CheckConstraint("scope = 'platform'", name="session_policies_platform_scope"),
        CheckConstraint("status = 'active'", name="session_policies_active_status"),
        CheckConstraint("version > 0", name="session_policies_positive_version"),
        CheckConstraint("idle_timeout_seconds BETWEEN 60 AND 86400", name="session_policies_idle_range"),
        CheckConstraint("absolute_timeout_seconds BETWEEN 300 AND 2592000", name="session_policies_absolute_range"),
        CheckConstraint("max_concurrent_sessions BETWEEN 1 AND 100", name="session_policies_concurrency_range"),
        CheckConstraint("activity_write_interval_seconds BETWEEN 30 AND 3600", name="session_policies_touch_range"),
        CheckConstraint(
            "activity_write_interval_seconds < idle_timeout_seconds",
            name="session_policies_touch_before_idle",
        ),
        CheckConstraint(
            "activity_write_interval_seconds < remember_idle_timeout_seconds",
            name="session_policies_touch_before_remember_idle",
        ),
        CheckConstraint(
            "remember_idle_timeout_seconds BETWEEN 60 AND 604800", name="session_policies_remember_idle_range"
        ),
        CheckConstraint(
            "remember_absolute_timeout_seconds BETWEEN 300 AND 31536000",
            name="session_policies_remember_absolute_range",
        ),
        CheckConstraint("retention_days BETWEEN 1 AND 3650", name="session_policies_retention_range"),
        CheckConstraint("idle_timeout_seconds <= absolute_timeout_seconds", name="session_policies_standard_coherent"),
        CheckConstraint(
            "remember_idle_timeout_seconds <= remember_absolute_timeout_seconds",
            name="session_policies_remember_coherent",
        ),
        UniqueConstraint("scope", name="uq_identity_session_policy_scope"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    absolute_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrent_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_write_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    remember_me_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    remember_idle_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    remember_absolute_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuthenticationEvent(IdentityBase):
    __tablename__ = "authentication_events"
    __table_args__ = (
        Index("ix_identity_auth_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_identity_auth_events_email_occurred", "email_normalized", "occurred_at"),
        Index("ix_identity_auth_events_type_occurred", "event_type", "occurred_at"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True
    )
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.auth_sessions.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class LoginThrottle(IdentityBase):
    __tablename__ = "login_throttles"
    __table_args__ = (
        UniqueConstraint("email_normalized", "origin", name="uq_identity_login_throttle_account_origin"),
        Index("ix_identity_login_throttles_blocked_until", "blocked_until"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
