from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.providers.base import ProviderAdapter, ProviderCapabilities, ProviderHealth

JsonMapping = Mapping[str, Any]


class ProviderReadinessStatus(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderReadinessPolicy:
    execution_enabled: bool = False
    require_generation_capability: bool = True
    active_health_check_enabled: bool = False
    accepted_health_statuses: frozenset[str] = frozenset({"healthy", "ready", "ok"})


@dataclass(frozen=True)
class ProviderReadinessResult:
    status: ProviderReadinessStatus
    ready: bool
    adapter_type: str
    reason: str
    capabilities: ProviderCapabilities
    health: ProviderHealth | None = None
    active_check_performed: bool = False
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class ProviderReadinessBoundary(Protocol):
    def evaluate(
        self,
        adapter: ProviderAdapter,
        *,
        policy: ProviderReadinessPolicy,
    ) -> ProviderReadinessResult: ...


class DefaultProviderReadinessBoundary:
    def evaluate(
        self,
        adapter: ProviderAdapter,
        *,
        policy: ProviderReadinessPolicy,
    ) -> ProviderReadinessResult:
        capabilities = adapter.capabilities()
        adapter_type = adapter.adapter_type

        if not policy.execution_enabled:
            return ProviderReadinessResult(
                status=ProviderReadinessStatus.DISABLED,
                ready=False,
                adapter_type=adapter_type,
                reason="provider_execution_disabled",
                capabilities=capabilities,
                active_check_performed=False,
                metadata={"network_call_performed": False},
            )

        if policy.require_generation_capability and not capabilities.generation:
            return ProviderReadinessResult(
                status=ProviderReadinessStatus.NOT_READY,
                ready=False,
                adapter_type=adapter_type,
                reason="generation_capability_unavailable",
                capabilities=capabilities,
                active_check_performed=False,
                metadata={"network_call_performed": False},
            )

        if not policy.active_health_check_enabled:
            return ProviderReadinessResult(
                status=ProviderReadinessStatus.UNKNOWN,
                ready=False,
                adapter_type=adapter_type,
                reason="active_health_check_disabled",
                capabilities=capabilities,
                active_check_performed=False,
                metadata={"network_call_performed": False},
            )

        if not capabilities.health_check:
            return ProviderReadinessResult(
                status=ProviderReadinessStatus.UNKNOWN,
                ready=False,
                adapter_type=adapter_type,
                reason="health_check_not_supported",
                capabilities=capabilities,
                active_check_performed=False,
                metadata={"network_call_performed": False},
            )

        health = adapter.health_check()
        normalized_status = health.status.strip().lower()
        if normalized_status in policy.accepted_health_statuses:
            return ProviderReadinessResult(
                status=ProviderReadinessStatus.READY,
                ready=True,
                adapter_type=adapter_type,
                reason="provider_ready",
                capabilities=capabilities,
                health=health,
                active_check_performed=True,
            )

        if normalized_status in {"degraded", "warning"}:
            status = ProviderReadinessStatus.DEGRADED
            reason = "provider_degraded"
        elif normalized_status == "disabled":
            status = ProviderReadinessStatus.DISABLED
            reason = "provider_disabled"
        else:
            status = ProviderReadinessStatus.NOT_READY
            reason = "provider_health_check_failed"

        return ProviderReadinessResult(
            status=status,
            ready=False,
            adapter_type=adapter_type,
            reason=reason,
            capabilities=capabilities,
            health=health,
            active_check_performed=True,
        )
