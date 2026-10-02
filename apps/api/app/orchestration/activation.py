from dataclasses import dataclass
from enum import StrEnum


class ActivationStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ExecutionFeatureFlags:
    runtime_execution_enabled: bool = False
    provider_execution_enabled: bool = False
    secret_resolution_enabled: bool = False
    active_health_checks_enabled: bool = False
    retries_enabled: bool = False
    audit_enabled: bool = True
    idempotency_enabled: bool = True


@dataclass(frozen=True)
class ExecutionActivationContext:
    generation_allowed: bool
    assisted_mode_requested: bool
    runtime_resolution_complete: bool
    prompt_renderer_available: bool
    guardrails_available: bool
    provider_adapter_available: bool
    provider_ready: bool
    secret_reference_available: bool
    audit_sink_available: bool
    idempotency_store_available: bool


@dataclass(frozen=True)
class ExecutionActivationDecision:
    status: ActivationStatus
    allowed: bool
    reason: str


class ExecutionActivationPolicy:
    def evaluate(
        self, *, flags: ExecutionFeatureFlags, context: ExecutionActivationContext
    ) -> ExecutionActivationDecision:
        checks = [
            (not flags.runtime_execution_enabled, ActivationStatus.DISABLED, "runtime_execution_disabled"),
            (not context.generation_allowed, ActivationStatus.BLOCKED, "generation_not_allowed"),
            (not context.assisted_mode_requested, ActivationStatus.BLOCKED, "assisted_mode_not_requested"),
            (not context.runtime_resolution_complete, ActivationStatus.BLOCKED, "runtime_resolution_incomplete"),
            (not context.prompt_renderer_available, ActivationStatus.BLOCKED, "prompt_renderer_unavailable"),
            (not context.guardrails_available, ActivationStatus.BLOCKED, "guardrails_unavailable"),
            (
                not flags.idempotency_enabled or not context.idempotency_store_available,
                ActivationStatus.BLOCKED,
                "idempotency_unavailable",
            ),
            (
                not flags.audit_enabled or not context.audit_sink_available,
                ActivationStatus.BLOCKED,
                "audit_unavailable",
            ),
            (not flags.provider_execution_enabled, ActivationStatus.DISABLED, "provider_execution_disabled"),
            (not context.provider_adapter_available, ActivationStatus.BLOCKED, "provider_adapter_unavailable"),
            (not context.provider_ready, ActivationStatus.BLOCKED, "provider_not_ready"),
            (not flags.secret_resolution_enabled, ActivationStatus.DISABLED, "secret_resolution_disabled"),
            (not context.secret_reference_available, ActivationStatus.BLOCKED, "secret_reference_unavailable"),
        ]
        for failed, status, reason in checks:
            if failed:
                return ExecutionActivationDecision(status, False, reason)
        return ExecutionActivationDecision(ActivationStatus.ENABLED, True, "execution_eligible")
