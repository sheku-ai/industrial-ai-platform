from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ResourceScopeType(StrEnum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    WORKLOAD = "workload"


class ResourceScopeInvariantError(ValueError):
    """Raised when an existing resource scope no longer satisfies its invariants."""


@dataclass(frozen=True)
class ResourceScope:
    scope_type: ResourceScopeType
    organization_id: UUID | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        normalized_resource_id = _normalize_optional_text(self.resource_id)
        object.__setattr__(self, "resource_id", normalized_resource_id)

        if self.scope_type is ResourceScopeType.PLATFORM:
            if self.organization_id is not None:
                raise ValueError("platform-scoped resources cannot have organization ownership")
            if normalized_resource_id is not None:
                raise ValueError("platform-scoped resources cannot have a tenant resource identifier")
            return

        if self.organization_id is None or self.organization_id.int == 0:
            raise ValueError(f"{self.scope_type.value}-scoped resources require an organization")

        if self.scope_type is ResourceScopeType.ORGANIZATION and normalized_resource_id is not None:
            raise ValueError("organization-scoped resources cannot have a workload resource identifier")

        if self.scope_type is ResourceScopeType.WORKLOAD and normalized_resource_id is None:
            raise ValueError("workload-scoped resources require a workload resource identifier")

    @classmethod
    def from_values(
        cls,
        *,
        scope_type: ResourceScopeType | str,
        organization_id: UUID | None,
        resource_id: str | None = None,
        scope_id: str | None = None,
    ) -> ResourceScope:
        normalized = ResourceScopeType(str(scope_type).strip().lower())
        resolved_resource_id = resource_id if resource_id is not None else scope_id
        if normalized is ResourceScopeType.PLATFORM:
            return cls.platform()
        if normalized is ResourceScopeType.ORGANIZATION:
            return cls.organization(organization_id)  # type: ignore[arg-type]
        return cls.workload(
            organization_id,  # type: ignore[arg-type]
            resource_id=resolved_resource_id,
        )

    @classmethod
    def from_persisted_assignment(
        cls,
        *,
        scope_type: str | None,
        scope_id: str | None,
        organization_id: UUID | None,
    ) -> ResourceScope | None:
        if not scope_type:
            if organization_id is None:
                return None
            return cls.organization(organization_id)
        try:
            normalized = ResourceScopeType(str(scope_type).strip().lower())
        except ValueError:
            return None
        if normalized is ResourceScopeType.PLATFORM:
            return cls.platform()
        if normalized is ResourceScopeType.ORGANIZATION:
            return cls.organization(organization_id)  # type: ignore[arg-type]
        return cls.workload(organization_id, resource_id=scope_id)  # type: ignore[arg-type]

    @classmethod
    def platform(cls) -> ResourceScope:
        return cls(scope_type=ResourceScopeType.PLATFORM)

    @classmethod
    def organization(cls, organization_id: UUID) -> ResourceScope:
        return cls(
            scope_type=ResourceScopeType.ORGANIZATION,
            organization_id=organization_id,
        )

    @classmethod
    def workload(cls, organization_id: UUID, *, resource_id: str | None) -> ResourceScope:
        return cls(
            scope_type=ResourceScopeType.WORKLOAD,
            organization_id=organization_id,
            resource_id=resource_id,
        )

    @property
    def scope_id(self) -> str:
        if self.scope_type is ResourceScopeType.PLATFORM:
            return ResourceScopeType.PLATFORM.value
        if self.scope_type is ResourceScopeType.ORGANIZATION:
            if self.organization_id is None:
                raise ResourceScopeInvariantError("organization scope is missing its organization identifier")
            return str(self.organization_id)
        if self.resource_id is None:
            raise ResourceScopeInvariantError("workload scope is missing its workload resource identifier")
        return self.resource_id

    @property
    def owns_organization(self) -> bool:
        return self.organization_id is not None

    def is_type(self, scope_type: ResourceScopeType | str) -> bool:
        return self.scope_type is ResourceScopeType(str(scope_type).strip().lower())

    def is_within(self, candidate: ResourceScope) -> bool:
        if candidate.scope_type is ResourceScopeType.PLATFORM:
            return self.scope_type is ResourceScopeType.PLATFORM
        if self.organization_id != candidate.organization_id:
            return False
        if candidate.scope_type is ResourceScopeType.ORGANIZATION:
            return self.scope_type in {ResourceScopeType.ORGANIZATION, ResourceScopeType.WORKLOAD}
        return self.scope_type is ResourceScopeType.WORKLOAD and self.scope_id == candidate.scope_id


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
