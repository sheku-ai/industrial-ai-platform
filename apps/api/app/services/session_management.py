from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.models import AuthSession, IdentityUser
from app.identity.service import IdentityService, utcnow
from app.models.audit import AuditEvent, AuditHistory


class SessionManagementError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class SessionManagementService:
    def __init__(
        self,
        identity_db: Session,
        platform_db: Session,
        settings: Settings,
        *,
        actor_reference: str,
        correlation_id: str | None,
    ) -> None:
        self.identity_db = identity_db
        self.platform_db = platform_db
        self.identity = IdentityService(identity_db, settings)
        self.actor_reference = actor_reference
        self.correlation_id = correlation_id

    def _user(self, user_id: uuid.UUID) -> IdentityUser:
        user = self.identity_db.get(IdentityUser, user_id)
        if user is None:
            raise SessionManagementError(404, "identity_not_found")
        return user

    def _audit(
        self,
        *,
        resource_type: str,
        resource_id: str,
        operation: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        metadata = {"operation": operation, "correlation_id": self.correlation_id}
        self.platform_db.add(
            AuditEvent(
                organization_id=None,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type=resource_type,
                resource_id=resource_id,
                summary=f"{operation} succeeded.",
                metadata_json=metadata,
            )
        )
        self.platform_db.add(
            AuditHistory(
                organization_id=None,
                entity_type=resource_type,
                entity_id=resource_id,
                action=operation,
                before_state=before or {},
                after_state=after or {},
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    @staticmethod
    def _policy_snapshot(policy) -> dict[str, Any]:
        return {
            key: getattr(policy, key)
            for key in (
                "idle_timeout_seconds",
                "absolute_timeout_seconds",
                "max_concurrent_sessions",
                "activity_write_interval_seconds",
                "remember_me_enabled",
                "remember_idle_timeout_seconds",
                "remember_absolute_timeout_seconds",
                "retention_days",
            )
        }

    def policy(self):
        return self.identity.session_policy()

    def update_policy(self, values: dict[str, Any], application_mode: str):
        policy = self.identity.session_policy(lock=True)
        before = self._policy_snapshot(policy)
        policy_changed = any(before[key] != value for key, value in values.items())
        if not policy_changed and application_mode == "new_sessions_only":
            return policy
        for key, value in values.items():
            setattr(policy, key, value)
        if policy_changed:
            policy.version += 1
        affected = 0
        if application_mode == "restrict_existing":
            affected = self._restrict_existing(policy)
        if not policy_changed and not affected:
            return policy
        policy.updated_by = self.actor_reference
        policy.updated_at = utcnow()
        after = self._policy_snapshot(policy)
        self.identity.add_event(
            "session_policy_updated",
            success=True,
            reason_code=application_mode,
            actor_reference=self.actor_reference,
            metadata={
                "before": before,
                "after": after,
                "application_mode": application_mode,
                "affected_sessions": affected,
            },
        )
        self._audit(
            resource_type="session_policy",
            resource_id=str(policy.id),
            operation="session_policy.updated",
            before=before,
            after={**after, "application_mode": application_mode, "affected_sessions": affected},
        )
        self.identity_db.commit()
        self.platform_db.commit()
        return policy

    def _restrict_existing(self, policy) -> int:
        now = utcnow()
        sessions = list(
            self.identity_db.scalars(
                select(AuthSession)
                .where(AuthSession.revoked_at.is_(None))
                .order_by(AuthSession.user_id, AuthSession.created_at, AuthSession.id)
                .with_for_update()
            ).all()
        )
        affected_ids: set[uuid.UUID] = set()
        by_user: dict[uuid.UUID, list[AuthSession]] = {}
        for item in sessions:
            original_remember_me = item.remember_me
            original_idle_timeout = item.idle_timeout_seconds
            original_policy_version = item.policy_version
            if item.remember_me and not policy.remember_me_enabled:
                item.remember_me = False
            configured_idle_seconds = (
                policy.remember_idle_timeout_seconds if item.remember_me else policy.idle_timeout_seconds
            )
            idle_seconds = min(item.idle_timeout_seconds, configured_idle_seconds)
            absolute_seconds = (
                policy.remember_absolute_timeout_seconds if item.remember_me else policy.absolute_timeout_seconds
            )
            restricted_absolute = min(item.absolute_expires_at, item.created_at + timedelta(seconds=absolute_seconds))
            restricted_idle = min(
                item.idle_expires_at,
                item.last_activity_at + timedelta(seconds=idle_seconds),
                restricted_absolute,
            )
            deadlines_changed = (
                restricted_absolute != item.absolute_expires_at or restricted_idle != item.idle_expires_at
            )
            if deadlines_changed:
                item.absolute_expires_at = restricted_absolute
                item.idle_expires_at = restricted_idle
            item.idle_timeout_seconds = idle_seconds
            item.policy_version = policy.version
            if (
                deadlines_changed
                or original_remember_me != item.remember_me
                or original_idle_timeout != item.idle_timeout_seconds
                or original_policy_version != item.policy_version
            ):
                item.updated_at = now
                affected_ids.add(item.id)
            reason = self.identity.session_status(item, now=now)
            if reason != "active":
                if self.identity.revoke_session(
                    item,
                    reason=reason,
                    actor_reference=self.actor_reference,
                ):
                    affected_ids.add(item.id)
            else:
                by_user.setdefault(item.user_id, []).append(item)
        for user_sessions in by_user.values():
            for item in user_sessions[: -policy.max_concurrent_sessions]:
                if self.identity.revoke_session(
                    item,
                    reason="concurrent_session_limit",
                    actor_reference=self.actor_reference,
                ):
                    affected_ids.add(item.id)
        return len(affected_ids)

    def sessions(
        self,
        user_id: uuid.UUID,
        *,
        status_filter: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        self._user(user_id)
        return {
            "user_id": user_id,
            **self.identity.list_sessions(
                user_id,
                status_filter=status_filter,
                offset=offset,
                limit=limit,
            ),
        }

    def revoke(self, user_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
        user = self._user(user_id)
        auth_session = self.identity_db.scalar(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        )
        if auth_session is None or auth_session.user_id != user.id:
            raise SessionManagementError(404, "session_not_found")
        changed = self.identity.revoke_session(
            auth_session,
            reason="administrative_revocation",
            user=user,
            actor_reference=self.actor_reference,
        )
        self._audit(
            resource_type="auth_session",
            resource_id=str(auth_session.id),
            operation="session.administratively_revoked",
            after={"user_id": str(user.id), "changed": changed},
        )
        self.identity_db.commit()
        self.platform_db.commit()
        return {
            "operation": "session.administratively_revoked",
            "outcome": "updated" if changed else "unchanged",
            "revoked_session_count": int(changed),
        }

    def revoke_all(self, user_id: uuid.UUID) -> dict[str, Any]:
        user = self._user(user_id)
        count = self.identity.revoke_user_sessions(
            user,
            reason="administrative_revocation",
            actor_reference=self.actor_reference,
        )
        self._audit(
            resource_type="global_identity",
            resource_id=str(user.id),
            operation="sessions.administratively_revoked",
            after={"revoked_session_count": count},
        )
        self.identity_db.commit()
        self.platform_db.commit()
        return {
            "operation": "sessions.administratively_revoked",
            "outcome": "updated" if count else "unchanged",
            "revoked_session_count": count,
        }
