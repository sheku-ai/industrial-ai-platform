from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.security.context import (
    ActorContext,
    ActorScope,
    ActorType,
    AuthenticationAssurance,
    AuthenticationMethod,
    OrganizationContext,
    RequestContext,
    RequestSource,
)


class IdentityResolutionError(RuntimeError):
    pass


class IdentityProviderUnavailable(IdentityResolutionError):
    pass


class ResolvedPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1, max_length=512)
    actor_id: str = Field(min_length=1, max_length=255)
    actor_type: ActorType
    organization_id: uuid.UUID | None = None
    organization_path: tuple[uuid.UUID, ...] = ()
    roles: frozenset[str] = frozenset()
    permission_claims: frozenset[str] = frozenset()
    scope: ActorScope
    service_identity: str | None = None
    method: AuthenticationMethod
    assurance: AuthenticationAssurance
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> ResolvedPrincipal:
        if self.scope == ActorScope.ORGANIZATION and self.organization_id is None:
            raise ValueError("organization-scoped principal requires organization_id")
        if self.scope == ActorScope.PLATFORM and self.organization_id is not None:
            raise ValueError("platform-scoped principal cannot carry organization_id")
        if self.actor_type == ActorType.SERVICE and not self.service_identity:
            raise ValueError("service principal requires service_identity")
        return self


class IdentityProvider(Protocol):
    def resolve(self, presented_value: str | None) -> ResolvedPrincipal: ...


@dataclass(frozen=True)
class DisabledIdentityProvider:
    def resolve(self, presented_value: str | None) -> ResolvedPrincipal:
        del presented_value
        raise IdentityProviderUnavailable("identity provider is not configured")


def build_request_context(
    principal: ResolvedPrincipal,
    *,
    correlation_id: str,
    source: RequestSource,
) -> RequestContext:
    organization = None
    if principal.organization_id is not None:
        organization = OrganizationContext(
            organization_id=principal.organization_id,
            organization_path=principal.organization_path or (principal.organization_id,),
            membership_source="identity_provider",
            scope_attributes=dict(principal.attributes),
        )

    actor = ActorContext(
        actor_id=principal.actor_id,
        actor_type=principal.actor_type,
        subject=principal.subject,
        roles=principal.roles,
        permission_claims=principal.permission_claims,
        scope=principal.scope,
        service_identity=principal.service_identity,
        authentication_assurance=principal.assurance,
    )

    return RequestContext(
        correlation_id=correlation_id,
        actor=actor,
        organization=organization,
        authentication_method=principal.method,
        source=source,
        policy_attributes=dict(principal.attributes),
    )
