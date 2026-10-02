from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition
from app.services.ingestion_contracts import IngestionContractError, ResolvedAdapterConfiguration


@dataclass(frozen=True)
class IngestionPipelineProfileSnapshot:
    profile_id: UUID
    organization_id: UUID
    revision: str
    enabled: bool
    deployment_edition: DeploymentEdition
    default_adapter_key: str | None
    adapter_policies: tuple[AdapterPolicy, ...]
    adapter_versions: Mapping[str, str]
    adapter_settings: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not self.revision.strip():
            raise IngestionContractError("pipeline profile revision is required")
        if self.default_adapter_key is not None and not self.default_adapter_key.strip():
            raise IngestionContractError("default_adapter_key cannot be blank")

        normalized_versions: dict[str, str] = {}
        for adapter_key, version in self.adapter_versions.items():
            key = adapter_key.strip()
            value = version.strip()
            if not key or not value:
                raise IngestionContractError("adapter versions require non-blank key and version")
            normalized_versions[key] = value

        copied_settings = {adapter_key: dict(settings) for adapter_key, settings in self.adapter_settings.items()}
        object.__setattr__(self, "adapter_versions", normalized_versions)
        object.__setattr__(self, "adapter_settings", copied_settings)


class IngestionConfigurationRepository(Protocol):
    def get_pipeline_profile(
        self,
        organization_id: UUID,
        profile_id: UUID,
    ) -> IngestionPipelineProfileSnapshot | None: ...


@dataclass(frozen=True)
class ResolvedIngestionConfiguration:
    profile: IngestionPipelineProfileSnapshot
    adapter_configuration: ResolvedAdapterConfiguration


class IngestionConfigurationService:
    """Load profiles and resolve exact adapter configuration snapshots."""

    def __init__(self, repository: IngestionConfigurationRepository) -> None:
        self._repository = repository

    def get_profile(
        self,
        organization_id: UUID,
        profile_id: UUID,
    ) -> IngestionPipelineProfileSnapshot:
        profile = self._repository.get_pipeline_profile(organization_id, profile_id)
        if profile is None:
            raise IngestionContractError("ingestion pipeline profile was not found")
        if profile.organization_id != organization_id:
            raise IngestionContractError("pipeline profile organization mismatch")
        if not profile.enabled:
            raise IngestionContractError("ingestion pipeline profile is disabled")
        return profile

    def resolve_for_adapter(
        self,
        profile: IngestionPipelineProfileSnapshot,
        adapter_key: str,
    ) -> ResolvedIngestionConfiguration:
        selected = adapter_key.strip()
        if not selected:
            raise IngestionContractError("adapter key cannot be blank")

        enabled = {policy.adapter_key for policy in profile.adapter_policies if policy.enabled}
        if selected not in enabled:
            raise IngestionContractError("requested adapter is not enabled by profile policy")

        adapter_version = profile.adapter_versions.get(selected)
        if adapter_version is None:
            raise IngestionContractError("selected adapter version is not configured")

        return ResolvedIngestionConfiguration(
            profile=profile,
            adapter_configuration=ResolvedAdapterConfiguration(
                adapter_key=selected,
                adapter_version=adapter_version,
                pipeline_profile_revision=profile.revision,
                settings=profile.adapter_settings.get(selected, {}),
            ),
        )

    def resolve(
        self,
        organization_id: UUID,
        profile_id: UUID,
        *,
        requested_adapter_key: str | None = None,
    ) -> ResolvedIngestionConfiguration:
        profile = self.get_profile(organization_id, profile_id)
        adapter_key = self._select_adapter_key(
            profile,
            requested_adapter_key=requested_adapter_key,
        )
        return self.resolve_for_adapter(profile, adapter_key)

    @staticmethod
    def _select_adapter_key(
        profile: IngestionPipelineProfileSnapshot,
        *,
        requested_adapter_key: str | None,
    ) -> str:
        enabled_policies = {policy.adapter_key: policy for policy in profile.adapter_policies if policy.enabled}

        if requested_adapter_key is not None:
            requested = requested_adapter_key.strip()
            if not requested:
                raise IngestionContractError("requested adapter key cannot be blank")
            if requested not in enabled_policies:
                raise IngestionContractError("requested adapter is not enabled by profile policy")
            return requested

        if profile.default_adapter_key is not None:
            if profile.default_adapter_key not in enabled_policies:
                raise IngestionContractError("default adapter is not enabled by profile policy")
            return profile.default_adapter_key

        if len(enabled_policies) == 1:
            return next(iter(enabled_policies))

        raise IngestionContractError("pipeline profile does not resolve a unique adapter")


def freeze_adapter_settings(
    settings: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    return {adapter_key: dict(values) for adapter_key, values in settings.items()}


def normalize_adapter_policies(
    policies: Sequence[AdapterPolicy],
) -> tuple[AdapterPolicy, ...]:
    seen: set[str] = set()
    normalized: list[AdapterPolicy] = []
    for policy in policies:
        if policy.adapter_key in seen:
            raise IngestionContractError(f"duplicate adapter policy: {policy.adapter_key}")
        seen.add(policy.adapter_key)
        normalized.append(policy)
    return tuple(normalized)
