from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActorType(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    SYSTEM = "system"


class ActorScope(StrEnum):
    ORGANIZATION = "organization"
    PLATFORM = "platform"


class AuthenticationMethod(StrEnum):
    BEARER = "bearer"
    SESSION = "session"
    API_KEY = "api_key"
    WORKLOAD_IDENTITY = "workload_identity"
    INTERNAL = "internal"
    NONE = "none"


class AuthenticationAssurance(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    LOW = "low"
    STANDARD = "standard"
    STRONG = "strong"


class RequestSource(StrEnum):
    API = "api"
    WORKER = "worker"
    SCHEDULER = "scheduler"
    CONNECTOR = "connector"
    INTERNAL = "internal"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _require_timezone_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class OrganizationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: uuid.UUID
    organization_path: tuple[uuid.UUID, ...] = ()
    membership_source: str = Field(min_length=1, max_length=128)
    scope_attributes: dict[str, Any] = Field(default_factory=dict)
    resolved_at: datetime = Field(default_factory=utc_now)

    @field_validator("resolved_at")
    @classmethod
    def validate_resolved_at(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value, "resolved_at")

    @model_validator(mode="after")
    def validate_path(self) -> OrganizationContext:
        if self.organization_path and self.organization_path[-1] != self.organization_id:
            raise ValueError("organization_path must end with organization_id")
        return self


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(min_length=1, max_length=255)
    actor_type: ActorType
    subject: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=255)
    roles: frozenset[str] = frozenset()
    permission_claims: frozenset[str] = frozenset()
    scope: ActorScope
    service_identity: str | None = Field(default=None, max_length=255)
    authentication_assurance: AuthenticationAssurance

    @model_validator(mode="after")
    def validate_actor(self) -> ActorContext:
        if self.actor_type == ActorType.SERVICE and not self.service_identity:
            raise ValueError("service actors require service_identity")
        if self.authentication_assurance == AuthenticationAssurance.UNAUTHENTICATED and (
            self.roles or self.permission_claims
        ):
            raise ValueError("unauthenticated actors cannot carry roles or permission claims")
        return self


class RequestContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    correlation_id: str = Field(min_length=1, max_length=255)
    actor: ActorContext
    organization: OrganizationContext | None = None
    authentication_method: AuthenticationMethod
    received_at: datetime = Field(default_factory=utc_now)
    source: RequestSource
    policy_attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value, "received_at")

    @model_validator(mode="after")
    def validate_scope(self) -> RequestContext:
        if self.actor.scope == ActorScope.ORGANIZATION and self.organization is None:
            raise ValueError("organization-scoped actors require organization context")
        if self.actor.scope == ActorScope.PLATFORM and self.organization is not None:
            raise ValueError("platform-scoped actors cannot use organization context as authority")
        if (
            self.authentication_method == AuthenticationMethod.NONE
            and self.actor.authentication_assurance != AuthenticationAssurance.UNAUTHENTICATED
        ):
            raise ValueError("authentication_method=none requires unauthenticated assurance")
        return self


class SecurityContextUnavailable(RuntimeError):
    pass


class RequestContextResolver(Protocol):
    def resolve(self, request: Any) -> RequestContext: ...


class DenyAllRequestContextResolver:
    """Fail-closed resolver used until authentication is implemented in Sprint 18.4."""

    def resolve(self, request: Any) -> RequestContext:
        del request
        raise SecurityContextUnavailable("authenticated request context is not configured")


def build_internal_service_context(
    *,
    service_identity: str,
    correlation_id: str,
    organization: OrganizationContext | None = None,
    roles: frozenset[str] = frozenset(),
    permission_claims: frozenset[str] = frozenset(),
    source: RequestSource = RequestSource.INTERNAL,
) -> RequestContext:
    """Construct an explicit trusted internal service context for tests and orchestration."""

    scope = ActorScope.ORGANIZATION if organization is not None else ActorScope.PLATFORM
    actor = ActorContext(
        actor_id=service_identity,
        actor_type=ActorType.SERVICE,
        subject=service_identity,
        roles=roles,
        permission_claims=permission_claims,
        scope=scope,
        service_identity=service_identity,
        authentication_assurance=AuthenticationAssurance.STRONG,
    )
    return RequestContext(
        correlation_id=correlation_id,
        actor=actor,
        organization=organization,
        authentication_method=AuthenticationMethod.INTERNAL,
        source=source,
    )
