from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.security.context import ActorScope, RequestContext


class AuthorizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resource: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    resource_organization_id: uuid.UUID | None = None
    resource_attributes: dict[str, Any] = Field(default_factory=dict)


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: str
    matched_permissions: tuple[str, ...] = ()
    evaluation_source: str = "default_policy_evaluator"


class PolicyEvaluator(Protocol):
    def evaluate(self, context: RequestContext, request: AuthorizationRequest) -> AuthorizationDecision: ...


@dataclass(frozen=True)
class DefaultPolicyEvaluator:
    """Deterministic claim evaluator with explicit default deny semantics."""

    def evaluate(self, context: RequestContext, request: AuthorizationRequest) -> AuthorizationDecision:
        if request.resource_organization_id is not None and context.actor.scope == ActorScope.ORGANIZATION:
            if context.organization is None:
                return AuthorizationDecision(allowed=False, reason="organization_context_missing")
            if context.organization.organization_id != request.resource_organization_id:
                return AuthorizationDecision(allowed=False, reason="cross_organization_access_denied")

        required = f"{request.resource}.{request.action}"
        resource_wildcard = f"{request.resource}.*"
        claims = context.actor.permission_claims
        matched = tuple(permission for permission in (required, resource_wildcard, "*") if permission in claims)

        if not matched:
            return AuthorizationDecision(allowed=False, reason="permission_not_granted")

        return AuthorizationDecision(
            allowed=True,
            reason="permission_granted",
            matched_permissions=matched,
        )


class AuthorizationDenied(PermissionError):
    def __init__(self, decision: AuthorizationDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


def require_authorized(
    context: RequestContext,
    request: AuthorizationRequest,
    evaluator: PolicyEvaluator | None = None,
) -> AuthorizationDecision:
    decision = (evaluator or DefaultPolicyEvaluator()).evaluate(context, request)
    if not decision.allowed:
        raise AuthorizationDenied(decision)
    return decision
