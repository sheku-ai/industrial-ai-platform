from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BLOCKED_GUARDRAIL_REF = "blocked-grounding-policy"


@dataclass(frozen=True)
class GuardrailResolution:
    """Resolved guardrail reference metadata."""

    guardrail_ref: str | None
    resolved: bool
    allowed: bool
    resolver: str = "reference_only_guardrail_resolver_v1"
    policy_ref: str | None = None
    error_code: str | None = None

    def as_runtime_options(self) -> dict[str, Any]:
        return {
            "guardrail_ref": self.guardrail_ref,
            "guardrail_resolved": self.resolved,
            "guardrail_allowed": self.allowed,
            "guardrail_resolver": self.resolver,
            "guardrail_policy_ref": self.policy_ref,
            "guardrail_error_code": self.error_code,
        }

    def as_metrics(self) -> dict[str, Any]:
        return self.as_runtime_options()


def resolve_guardrail_ref(guardrail_ref: str | None) -> GuardrailResolution:
    """Resolve a guardrail reference without enforcing registry-backed policy."""

    if guardrail_ref == BLOCKED_GUARDRAIL_REF:
        return GuardrailResolution(
            guardrail_ref=guardrail_ref,
            resolved=True,
            allowed=False,
            policy_ref=guardrail_ref,
            error_code="guardrail_blocked",
        )

    return GuardrailResolution(
        guardrail_ref=guardrail_ref,
        resolved=True,
        allowed=True,
        policy_ref=guardrail_ref or "default-grounding-policy",
    )
