from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.services.ingestion_contracts import IngestionAdapter, IngestionContractError


class DeploymentEdition(StrEnum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class AdapterPolicy:
    adapter_key: str
    enabled: bool = True
    priority: int | None = None
    allowed_media_types: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.adapter_key.strip():
            raise IngestionContractError("adapter_key is required")
        if self.priority is not None and self.priority < 0:
            raise IngestionContractError("adapter priority must be non-negative")

        normalized_media_types = frozenset(_normalize_media_type(value) for value in self.allowed_media_types)
        object.__setattr__(self, "allowed_media_types", normalized_media_types)


@dataclass(frozen=True)
class AdapterResolutionRequest:
    declared_media_type: str
    detected_media_type: str
    deployment_edition: DeploymentEdition
    adapter_hint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declared_media_type",
            _normalize_media_type(self.declared_media_type),
        )
        object.__setattr__(
            self,
            "detected_media_type",
            _normalize_media_type(self.detected_media_type),
        )
        if self.adapter_hint is not None:
            normalized_hint = self.adapter_hint.strip()
            object.__setattr__(self, "adapter_hint", normalized_hint or None)


@dataclass(frozen=True)
class AdapterResolutionCandidate:
    adapter_key: str
    effective_priority: int
    hinted: bool


@dataclass(frozen=True)
class AdapterResolutionResult:
    adapter: IngestionAdapter
    candidates: tuple[AdapterResolutionCandidate, ...]
    selected_by_hint: bool
    declared_media_type_matches: bool


class IngestionAdapterResolver:
    """Resolve adapters from technical capabilities and policy snapshots.

    This resolver is intentionally persistence-neutral. A later configuration
    service may load AdapterPolicy values from PostgreSQL and pass them here.
    """

    def __init__(self, adapters: Iterable[IngestionAdapter]) -> None:
        registry: dict[str, IngestionAdapter] = {}
        for adapter in adapters:
            key = adapter.adapter_key.strip()
            if not key:
                raise IngestionContractError("registered adapter key is required")
            if key in registry:
                raise IngestionContractError(f"adapter already registered: {key}")
            registry[key] = adapter
        self._adapters = registry

    def resolve(
        self,
        request: AdapterResolutionRequest,
        policies: Sequence[AdapterPolicy],
    ) -> AdapterResolutionResult:
        policy_by_key = _index_policies(policies)
        candidates: list[tuple[IngestionAdapter, AdapterResolutionCandidate]] = []

        for adapter in self._adapters.values():
            policy = policy_by_key.get(adapter.adapter_key)
            if policy is not None and not policy.enabled:
                continue
            if not _edition_allowed(adapter, request.deployment_edition):
                continue
            if request.detected_media_type not in adapter.capabilities.supported_media_types:
                continue
            if (
                policy is not None
                and policy.allowed_media_types
                and request.detected_media_type not in policy.allowed_media_types
            ):
                continue

            effective_priority = (
                policy.priority if policy is not None and policy.priority is not None else adapter.capabilities.priority
            )
            hinted = request.adapter_hint == adapter.adapter_key
            candidates.append(
                (
                    adapter,
                    AdapterResolutionCandidate(
                        adapter_key=adapter.adapter_key,
                        effective_priority=effective_priority,
                        hinted=hinted,
                    ),
                )
            )

        if not candidates:
            raise IngestionContractError("no enabled ingestion adapter supports the detected media type")

        candidates.sort(
            key=lambda item: (
                0 if item[1].hinted else 1,
                item[1].effective_priority,
                item[1].adapter_key,
            )
        )

        selected_adapter, selected_candidate = candidates[0]
        return AdapterResolutionResult(
            adapter=selected_adapter,
            candidates=tuple(candidate for _, candidate in candidates),
            selected_by_hint=selected_candidate.hinted,
            declared_media_type_matches=(request.declared_media_type == request.detected_media_type),
        )

    def registered_adapter_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def _index_policies(policies: Sequence[AdapterPolicy]) -> Mapping[str, AdapterPolicy]:
    indexed: dict[str, AdapterPolicy] = {}
    for policy in policies:
        if policy.adapter_key in indexed:
            raise IngestionContractError(f"duplicate adapter policy: {policy.adapter_key}")
        indexed[policy.adapter_key] = policy
    return indexed


def _edition_allowed(
    adapter: IngestionAdapter,
    edition: DeploymentEdition,
) -> bool:
    if edition == DeploymentEdition.COMMUNITY:
        return adapter.capabilities.community_available
    if edition == DeploymentEdition.ENTERPRISE:
        return adapter.capabilities.enterprise_available
    raise IngestionContractError(f"unsupported deployment edition: {edition}")


def _normalize_media_type(value: str) -> str:
    normalized = value.split(";", 1)[0].strip().lower()
    if not normalized or "/" not in normalized:
        raise IngestionContractError("media type must use type/subtype form")
    return normalized
