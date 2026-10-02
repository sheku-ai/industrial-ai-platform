from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Any

from fastapi import Request
from sqlalchemy import and_, case, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.contracts import AuthenticatedPrincipal
from app.identity.models import (
    AuthenticationEvent,
    AuthSession,
    IdentityUser,
    LoginThrottle,
    OrganizationMembership,
    PasswordCredential,
    SessionPolicy,
)
from app.identity.passwords import PasswordManager
from app.security.client_ip import resolve_client_ip


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    normalized = str(email).strip().casefold()
    if not normalized or len(normalized) > 320 or "@" not in normalized:
        raise ValueError("invalid_email")
    return normalized


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def normalize_username(username: str) -> str:
    normalized = str(username).strip().casefold()
    if not normalized or len(normalized) > 128 or USERNAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("invalid_username")
    return normalized


def username_from_email(email: str) -> str:
    local_part = normalize_email(email).split("@", 1)[0]
    normalized = re.sub(r"[^a-z0-9._-]+", "-", local_part).strip("._-")
    return normalize_username(normalized)


def available_username_from_email(session: Session, email: str) -> str:
    base = username_from_email(email)
    if session.scalar(select(IdentityUser.id).where(IdentityUser.username == base)) is None:
        return base
    digest = hashlib.sha256(normalize_email(email).encode()).hexdigest()[:8]
    return f"{base[:119]}-{digest}"


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded_text(value: str | None, maximum: int) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:maximum] or None


def request_origin(request: Request, settings: Settings) -> str:
    return resolve_client_ip(request, settings)


def audit_request_metadata(request: Request, settings: Settings) -> dict[str, str | None]:
    return {
        "correlation_id": bounded_text(
            str(getattr(request.state, "correlation_id", "") or request.headers.get("X-Request-ID", "")),
            128,
        ),
        "origin": request_origin(request, settings),
        "user_agent": bounded_text(request.headers.get("User-Agent"), 512),
    }


class IdentityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self._passwords: PasswordManager | None = None

    @property
    def passwords(self) -> PasswordManager:
        if self._passwords is None:
            self._passwords = PasswordManager(self.settings)
        return self._passwords

    def active_memberships(self, user_id) -> tuple[OrganizationMembership, ...]:
        statement = (
            select(OrganizationMembership)
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == "active",
            )
            .order_by(OrganizationMembership.organization_id, OrganizationMembership.id)
        )
        return tuple(self.session.scalars(statement).all())

    def session_policy(self, *, lock: bool = False, shared_lock: bool = False) -> SessionPolicy:
        statement = select(SessionPolicy).where(
            SessionPolicy.scope == "platform",
            SessionPolicy.status == "active",
        )
        policy = self.session.scalar(statement.with_for_update(read=shared_lock) if lock else statement)
        if policy is None:
            raise RuntimeError("platform_session_policy_not_configured")
        return policy

    def lock_user_session_lifecycle(self, user_id) -> IdentityUser | None:
        user = self.session.scalar(select(IdentityUser).where(IdentityUser.id == user_id).with_for_update())
        if user is None:
            return None
        lock_material = f"auth-session|{user_id}".encode()
        lock_key = int.from_bytes(
            hashlib.blake2b(lock_material, digest_size=8).digest(),
            byteorder="big",
            signed=True,
        )
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        return user

    @staticmethod
    def session_status(auth_session: AuthSession, *, now: datetime | None = None) -> str:
        observed_at = now or utcnow()
        if auth_session.revoked_at is not None:
            return auth_session.revocation_reason or "revoked"
        if auth_session.absolute_expires_at <= observed_at:
            return "absolute_timeout"
        if auth_session.idle_expires_at <= observed_at:
            return "idle_timeout"
        return "active"

    def session_read(self, auth_session: AuthSession, *, current_session_id=None) -> dict[str, Any]:
        return {
            "id": auth_session.id,
            "current": auth_session.id == current_session_id,
            "created_at": auth_session.created_at,
            "last_activity_at": auth_session.last_activity_at,
            "idle_expires_at": auth_session.idle_expires_at,
            "absolute_expires_at": auth_session.absolute_expires_at,
            "revoked_at": auth_session.revoked_at,
            "revocation_reason": auth_session.revocation_reason,
            "remember_me": auth_session.remember_me,
            "client_ip": auth_session.client_ip,
            "user_agent": auth_session.user_agent,
            "status": self.session_status(auth_session),
        }

    def list_sessions(
        self,
        user_id,
        *,
        current_session_id=None,
        status_filter: str = "all",
        offset: int = 0,
        limit: int = 10,
    ) -> dict[str, Any]:
        now = utcnow()
        effectively_active = and_(
            AuthSession.revoked_at.is_(None),
            AuthSession.idle_expires_at > now,
            AuthSession.absolute_expires_at > now,
        )
        expired = or_(
            AuthSession.revocation_reason.in_(("idle_timeout", "absolute_timeout")),
            and_(
                AuthSession.revoked_at.is_(None),
                or_(AuthSession.idle_expires_at <= now, AuthSession.absolute_expires_at <= now),
            ),
        )
        revoked = and_(
            AuthSession.revoked_at.is_not(None),
            or_(
                AuthSession.revocation_reason.is_(None),
                AuthSession.revocation_reason.not_in(("idle_timeout", "absolute_timeout")),
            ),
        )
        predicates = {
            "all": None,
            "active": effectively_active,
            "expired": expired,
            "revoked": revoked,
        }
        status_predicate = predicates.get(status_filter)
        if status_filter not in predicates:
            raise ValueError("invalid_session_status_filter")
        filters = [AuthSession.user_id == user_id]
        if status_predicate is not None:
            filters.append(status_predicate)
        total = int(self.session.scalar(select(func.count(AuthSession.id)).where(*filters)) or 0)
        active_order = case((effectively_active, 0), else_=1)
        ordering = [active_order, AuthSession.created_at.desc(), AuthSession.id.desc()]
        if current_session_id is not None:
            ordering.insert(0, case((AuthSession.id == current_session_id, 0), else_=1))
        rows = self.session.scalars(
            select(AuthSession)
            .where(*filters)
            .order_by(*ordering)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "sessions": [self.session_read(item, current_session_id=current_session_id) for item in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
            "status_filter": status_filter,
        }

    def revoke_session(
        self,
        auth_session: AuthSession,
        *,
        reason: str,
        request: Request | None = None,
        user: IdentityUser | None = None,
        actor_reference: str | None = None,
    ) -> bool:
        if auth_session.revoked_at is not None:
            return False
        now = utcnow()
        auth_session.revoked_at = now
        auth_session.updated_at = now
        auth_session.revocation_reason = reason
        resolved_user = user or self.session.get(IdentityUser, auth_session.user_id)
        self.add_event(
            "session_revoked",
            success=True,
            request=request,
            user=resolved_user,
            auth_session=auth_session,
            reason_code=reason,
            actor_reference=actor_reference,
        )
        return True

    def revoke_user_sessions(
        self,
        user: IdentityUser,
        *,
        reason: str,
        request: Request | None = None,
        exclude_session_id=None,
        actor_reference: str | None = None,
    ) -> int:
        statement = (
            select(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if exclude_session_id is not None:
            statement = statement.where(AuthSession.id != exclude_session_id)
        return sum(
            self.revoke_session(
                item,
                reason=reason,
                request=request,
                user=user,
                actor_reference=actor_reference,
            )
            for item in self.session.scalars(statement).all()
        )

    def add_event(
        self,
        event_type: str,
        *,
        success: bool,
        request: Request | None = None,
        user: IdentityUser | None = None,
        email_normalized: str | None = None,
        auth_session: AuthSession | None = None,
        reason_code: str | None = None,
        actor_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuthenticationEvent:
        request_metadata = audit_request_metadata(request, self.settings) if request is not None else {}
        event = AuthenticationEvent(
            user_id=user.id if user is not None else None,
            email_normalized=email_normalized or (user.email_normalized if user is not None else None),
            event_type=bounded_text(event_type, 64) or "unknown",
            success=success,
            session_id=auth_session.id if auth_session is not None else None,
            correlation_id=request_metadata.get("correlation_id"),
            origin=request_metadata.get("origin"),
            user_agent=request_metadata.get("user_agent"),
            reason_code=bounded_text(reason_code, 64),
            actor_reference=bounded_text(actor_reference, 255),
            metadata_json=metadata or {},
        )
        self.session.add(event)
        return event

    def throttle_status(
        self,
        email_normalized: str,
        origin: str,
        *,
        now: datetime,
    ) -> LoginThrottle | None:
        lock_material = f"{email_normalized}\0{origin}".encode()
        lock_key = int.from_bytes(
            hashlib.blake2b(lock_material, digest_size=8).digest(),
            byteorder="big",
            signed=True,
        )
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        throttle = self.session.scalar(
            select(LoginThrottle)
            .where(
                LoginThrottle.email_normalized == email_normalized,
                LoginThrottle.origin == origin,
            )
            .with_for_update()
        )
        if throttle is None:
            return None
        window = timedelta(seconds=self.settings.auth_attempt_window_seconds)
        if now - throttle.window_started_at >= window:
            self.session.delete(throttle)
            self.session.flush()
            return None
        return throttle

    def is_rate_limited(self, throttle: LoginThrottle | None, *, now: datetime) -> bool:
        return bool(throttle is not None and throttle.blocked_until is not None and throttle.blocked_until > now)

    def record_login_failure(
        self,
        email_normalized: str,
        origin: str,
        *,
        now: datetime,
        throttle: LoginThrottle | None,
    ) -> LoginThrottle:
        if throttle is None:
            throttle = LoginThrottle(
                email_normalized=email_normalized,
                origin=origin,
                failure_count=0,
                window_started_at=now,
            )
            self.session.add(throttle)
        throttle.failure_count += 1
        throttle.last_failed_at = now
        if throttle.failure_count >= self.settings.auth_attempt_threshold:
            exponent = throttle.failure_count - self.settings.auth_attempt_threshold
            block_seconds = min(
                self.settings.auth_attempt_block_max_seconds,
                self.settings.auth_attempt_block_base_seconds * (2**exponent),
            )
            throttle.blocked_until = now + timedelta(seconds=block_seconds)
        self.session.flush()
        return throttle

    def reset_login_throttle(self, email_normalized: str, origin: str) -> None:
        self.session.execute(
            delete(LoginThrottle).where(
                LoginThrottle.email_normalized == email_normalized,
                LoginThrottle.origin == origin,
            )
        )

    def authenticate(
        self,
        *,
        email: str,
        password: str,
        request: Request,
        remember_me: bool = False,
    ) -> tuple[AuthenticatedPrincipal, str]:
        now = utcnow()
        identifier = str(email).strip().casefold()
        is_email = "@" in identifier
        email_normalized = normalize_email(identifier) if is_email else normalize_username(identifier)
        origin = request_origin(request, self.settings)
        throttle = self.throttle_status(email_normalized, origin, now=now)
        if self.is_rate_limited(throttle, now=now):
            self.passwords.equalize_unknown_user(password)
            self.add_event(
                "login_failed",
                success=False,
                request=request,
                email_normalized=email_normalized,
                reason_code="rate_limited",
            )
            self.session.commit()
            raise ValueError("login_rate_limited")

        user = self.session.scalar(
            select(IdentityUser).where(
                IdentityUser.email_normalized == email_normalized
                if is_email
                else IdentityUser.username == email_normalized
            )
        )
        if user is not None:
            user = self.lock_user_session_lifecycle(user.id)
        credential = (
            self.session.scalar(
                select(PasswordCredential).where(PasswordCredential.user_id == user.id).with_for_update()
            )
            if user is not None
            else None
        )
        if credential is None:
            self.passwords.equalize_unknown_user(password)
            verification_valid = False
            needs_rehash = False
        else:
            verification = self.passwords.verify(credential.password_hash, password)
            verification_valid = verification.valid
            needs_rehash = verification.needs_rehash

        if user is None or credential is None or not verification_valid:
            self.record_login_failure(
                email_normalized,
                origin,
                now=now,
                throttle=throttle,
            )
            self.add_event(
                "login_failed",
                success=False,
                request=request,
                user=user,
                email_normalized=email_normalized,
                reason_code="invalid_credentials",
            )
            self.session.commit()
            raise ValueError("invalid_credentials")

        if user.status != "active":
            self.record_login_failure(
                email_normalized,
                origin,
                now=now,
                throttle=throttle,
            )
            self.add_event(
                "account_suspended_rejection",
                success=False,
                request=request,
                user=user,
                reason_code="account_suspended",
            )
            self.session.commit()
            raise ValueError("invalid_credentials")

        if needs_rehash:
            credential.password_hash = self.passwords.hash_password(password)
            credential.algorithm = self.passwords.algorithm
            credential.parameters = self.passwords.parameters

        self.reset_login_throttle(email_normalized, origin)
        policy = self.session_policy(lock=True, shared_lock=True)
        remember = bool(remember_me and policy.remember_me_enabled)
        idle_seconds = policy.remember_idle_timeout_seconds if remember else policy.idle_timeout_seconds
        absolute_seconds = policy.remember_absolute_timeout_seconds if remember else policy.absolute_timeout_seconds
        existing_sessions = list(
            self.session.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .order_by(AuthSession.created_at, AuthSession.id)
                .with_for_update()
            ).all()
        )
        for existing in existing_sessions:
            status_code = self.session_status(existing, now=now)
            if status_code != "active":
                self.revoke_session(
                    existing,
                    reason=status_code,
                    request=request,
                    user=user,
                    actor_reference=str(user.id),
                )

        token = secrets.token_urlsafe(32)
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=hash_secret(token),
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(seconds=idle_seconds),
            absolute_expires_at=now + timedelta(seconds=absolute_seconds),
            idle_timeout_seconds=idle_seconds,
            policy_version=policy.version,
            remember_me=remember,
            client_ip=origin,
            user_agent=bounded_text(request.headers.get("User-Agent"), 512),
            updated_at=now,
            metadata_json={
                "origin": origin,
                "user_agent": bounded_text(request.headers.get("User-Agent"), 256),
            },
        )
        self.session.add(auth_session)
        self.session.flush()
        self.add_event(
            "session_created",
            success=True,
            request=request,
            user=user,
            auth_session=auth_session,
            actor_reference=str(user.id),
        )
        self.add_event(
            "login_succeeded",
            success=True,
            request=request,
            user=user,
            auth_session=auth_session,
            actor_reference=str(user.id),
        )
        active_sessions = [
            item for item in [*existing_sessions, auth_session] if self.session_status(item, now=now) == "active"
        ]
        for oldest in active_sessions[: -policy.max_concurrent_sessions]:
            self.revoke_session(
                oldest,
                reason="concurrent_session_limit",
                request=request,
                user=user,
                actor_reference=str(user.id),
            )
        memberships = self.active_memberships(user.id)
        self.session.commit()
        return AuthenticatedPrincipal(user=user, session=auth_session, memberships=memberships), token

    def resolve_session(
        self,
        token: str | None,
        *,
        request: Request | None = None,
        touch: bool = True,
    ) -> AuthenticatedPrincipal | None:
        if not token:
            return None
        now = utcnow()
        token_hash = hash_secret(token)
        auth_session = self.session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        if auth_session is None or not compare_digest(auth_session.token_hash, token_hash):
            return None
        if auth_session.revoked_at is not None:
            return None

        user = self.session.get(IdentityUser, auth_session.user_id)
        policy = self.session_policy()
        touch_due = now - auth_session.last_activity_at >= timedelta(seconds=policy.activity_write_interval_seconds)
        requires_mutation = (
            self.session_status(auth_session, now=now) != "active"
            or user is None
            or user.status != "active"
            or (touch and touch_due)
        )
        if requires_mutation:
            auth_session = self.session.scalar(
                select(AuthSession)
                .where(AuthSession.id == auth_session.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if auth_session is None or auth_session.revoked_at is not None:
                return None
            now = utcnow()
            session_status = self.session_status(auth_session, now=now)
            user = self.session.get(IdentityUser, auth_session.user_id)
            if session_status != "active":
                self.revoke_session(
                    auth_session,
                    reason=session_status,
                    request=request,
                    user=user,
                    actor_reference="system",
                )
                self.session.commit()
                return None
            if user is None or user.status != "active":
                self.revoke_session(
                    auth_session,
                    reason="identity_deactivated",
                    request=request,
                    user=user,
                    actor_reference="system",
                )
                self.session.commit()
                return None
            touch_due = now - auth_session.last_activity_at >= timedelta(seconds=policy.activity_write_interval_seconds)
        if touch and touch_due:
            auth_session.last_activity_at = now
            auth_session.idle_expires_at = min(
                now + timedelta(seconds=auth_session.idle_timeout_seconds),
                auth_session.absolute_expires_at,
            )
            auth_session.updated_at = now
            self.add_event(
                "session_activity_renewed",
                success=True,
                request=request,
                user=user,
                auth_session=auth_session,
                actor_reference=str(user.id),
            )
            self.session.commit()
        return AuthenticatedPrincipal(
            user=user,
            session=auth_session,
            memberships=self.active_memberships(user.id),
        )

    def rotate_csrf_token(self, principal: AuthenticatedPrincipal) -> str:
        token = secrets.token_urlsafe(self.settings.auth_csrf_token_bytes)
        principal.session.csrf_token_hash = hash_secret(token)
        self.session.commit()
        return token

    def validate_csrf(self, principal: AuthenticatedPrincipal, submitted_token: str | None) -> bool:
        expected = principal.session.csrf_token_hash
        if not expected or not submitted_token:
            return False
        return compare_digest(expected, hash_secret(submitted_token))

    def logout(
        self,
        principal: AuthenticatedPrincipal | None,
        *,
        request: Request,
    ) -> None:
        if principal is None or principal.session.revoked_at is not None:
            return
        self.revoke_session(
            principal.session,
            reason="logout",
            request=request,
            user=principal.user,
            actor_reference=principal.actor_reference,
        )
        self.add_event(
            "logout",
            success=True,
            request=request,
            user=principal.user,
            auth_session=principal.session,
            reason_code="logout",
            actor_reference=principal.actor_reference,
        )
        self.session.commit()

    def change_password(
        self,
        principal: AuthenticatedPrincipal,
        *,
        current_password: str,
        new_password: str,
        request: Request,
    ) -> None:
        locked_user = self.lock_user_session_lifecycle(principal.user.id)
        if locked_user is None:
            raise ValueError("invalid_current_password")
        credential = self.session.scalar(
            select(PasswordCredential).where(PasswordCredential.user_id == locked_user.id).with_for_update()
        )
        if credential is None or not self.passwords.verify(credential.password_hash, current_password).valid:
            raise ValueError("invalid_current_password")
        new_hash = self.passwords.hash_password(new_password)
        now = utcnow()
        credential.password_hash = new_hash
        credential.algorithm = self.passwords.algorithm
        credential.parameters = self.passwords.parameters
        credential.password_changed_at = now
        locked_user.must_change_password = False
        self.revoke_user_sessions(
            locked_user,
            reason="password_changed",
            request=request,
            actor_reference=principal.actor_reference,
        )
        self.add_event(
            "password_changed",
            success=True,
            request=request,
            user=locked_user,
            auth_session=principal.session,
            actor_reference=principal.actor_reference,
        )
        self.session.commit()

    def purge_historical_sessions(self, *, execute: bool = False) -> int:
        policy = self.session_policy()
        cutoff = utcnow() - timedelta(days=policy.retention_days)
        candidates = list(
            self.session.scalars(
                select(AuthSession).where(
                    or_(
                        AuthSession.revoked_at <= cutoff,
                        AuthSession.absolute_expires_at <= cutoff,
                        AuthSession.idle_expires_at <= cutoff,
                    )
                )
            ).all()
        )
        if execute and candidates:
            for item in candidates:
                self.session.delete(item)
            self.session.commit()
        return len(candidates)
