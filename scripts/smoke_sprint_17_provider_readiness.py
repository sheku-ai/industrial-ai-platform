from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    DefaultProviderReadinessBoundary,
    ProviderReadinessBoundary,
    ProviderReadinessPolicy,
    ProviderReadinessStatus,
)
from app.providers.base import ProviderCapabilities, ProviderHealth
from app.providers.disabled import DisabledProviderAdapter


class HealthyAdapter:
    adapter_type = "healthy-test"

    def __init__(self) -> None:
        self.health_calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(generation=True, health_check=True)

    def health_check(self) -> ProviderHealth:
        self.health_calls += 1
        return ProviderHealth(status="healthy", latency_ms=5)

    def execute(self, request):
        raise AssertionError("execute must not be called")


class NoGenerationAdapter(HealthyAdapter):
    adapter_type = "no-generation"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(generation=False, health_check=True)


def main() -> None:
    boundary = DefaultProviderReadinessBoundary()
    assert isinstance(boundary, ProviderReadinessBoundary)

    healthy = HealthyAdapter()
    disabled = boundary.evaluate(
        healthy,
        policy=ProviderReadinessPolicy(execution_enabled=False),
    )
    assert disabled.status == ProviderReadinessStatus.DISABLED
    assert disabled.ready is False
    assert disabled.active_check_performed is False
    assert healthy.health_calls == 0

    passive = boundary.evaluate(
        healthy,
        policy=ProviderReadinessPolicy(
            execution_enabled=True,
            active_health_check_enabled=False,
        ),
    )
    assert passive.status == ProviderReadinessStatus.UNKNOWN
    assert passive.ready is False
    assert passive.active_check_performed is False
    assert healthy.health_calls == 0

    no_generation = boundary.evaluate(
        NoGenerationAdapter(),
        policy=ProviderReadinessPolicy(
            execution_enabled=True,
            active_health_check_enabled=True,
        ),
    )
    assert no_generation.status == ProviderReadinessStatus.NOT_READY
    assert no_generation.reason == "generation_capability_unavailable"

    ready = boundary.evaluate(
        healthy,
        policy=ProviderReadinessPolicy(
            execution_enabled=True,
            active_health_check_enabled=True,
        ),
    )
    assert ready.status == ProviderReadinessStatus.READY
    assert ready.ready is True
    assert ready.active_check_performed is True
    assert healthy.health_calls == 1

    disabled_adapter = DisabledProviderAdapter()
    disabled_provider = boundary.evaluate(
        disabled_adapter,
        policy=ProviderReadinessPolicy(
            execution_enabled=True,
            active_health_check_enabled=True,
        ),
    )
    assert disabled_provider.status == ProviderReadinessStatus.NOT_READY
    assert disabled_provider.ready is False
    assert disabled_provider.active_check_performed is False

    print({
        "status": "passed",
        "readiness_contract": True,
        "execution_disabled_short_circuit": True,
        "passive_mode_no_probe": True,
        "generation_capability_required": True,
        "active_health_check_opt_in": True,
        "disabled_provider_not_ready": True,
        "provider_execution_performed": False,
        "network_call_performed": False,
        "generation_performed": False,
    })


if __name__ == "__main__":
    main()
