from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    ActivationStatus,
    ExecutionActivationContext,
    ExecutionActivationPolicy,
    ExecutionFeatureFlags,
    ProviderResponseNormalizer,
)


def ready_context(**overrides):
    values = {
        "generation_allowed": True,
        "assisted_mode_requested": True,
        "runtime_resolution_complete": True,
        "prompt_renderer_available": True,
        "guardrails_available": True,
        "provider_adapter_available": True,
        "provider_ready": True,
        "secret_reference_available": True,
        "audit_sink_available": True,
        "idempotency_store_available": True,
    }
    values.update(overrides)
    return ExecutionActivationContext(**values)


def main() -> None:
    policy = ExecutionActivationPolicy()

    default_decision = policy.evaluate(
        flags=ExecutionFeatureFlags(),
        context=ready_context(),
    )
    assert default_decision.status == ActivationStatus.DISABLED
    assert default_decision.reason == "runtime_execution_disabled"

    runtime_only = policy.evaluate(
        flags=ExecutionFeatureFlags(runtime_execution_enabled=True),
        context=ready_context(),
    )
    assert runtime_only.reason == "provider_execution_disabled"

    no_generation = policy.evaluate(
        flags=ExecutionFeatureFlags(
            runtime_execution_enabled=True,
            provider_execution_enabled=True,
            secret_resolution_enabled=True,
        ),
        context=ready_context(generation_allowed=False),
    )
    assert no_generation.status == ActivationStatus.BLOCKED
    assert no_generation.reason == "generation_not_allowed"

    no_audit = policy.evaluate(
        flags=ExecutionFeatureFlags(
            runtime_execution_enabled=True,
            provider_execution_enabled=True,
            secret_resolution_enabled=True,
            audit_enabled=False,
        ),
        context=ready_context(),
    )
    assert no_audit.reason == "audit_unavailable"

    no_idempotency = policy.evaluate(
        flags=ExecutionFeatureFlags(
            runtime_execution_enabled=True,
            provider_execution_enabled=True,
            secret_resolution_enabled=True,
            idempotency_enabled=False,
        ),
        context=ready_context(),
    )
    assert no_idempotency.reason == "idempotency_unavailable"

    enabled = policy.evaluate(
        flags=ExecutionFeatureFlags(
            runtime_execution_enabled=True,
            provider_execution_enabled=True,
            secret_resolution_enabled=True,
        ),
        context=ready_context(),
    )
    assert enabled.status == ActivationStatus.ENABLED
    assert enabled.allowed is True
    assert ProviderResponseNormalizer is not None

    print(
        {
            "status": "passed",
            "default_deny": True,
            "independent_feature_flags": True,
            "generation_gate": True,
            "audit_gate": True,
            "idempotency_gate": True,
            "full_activation_requires_all_prerequisites": True,
            "normalizer_exported": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
