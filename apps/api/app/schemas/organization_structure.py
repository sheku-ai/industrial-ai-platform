from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_REFERENCE_PATTERN = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|local:[a-zA-Z0-9._-]{1,128})$"
)
METADATA_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")
SENSITIVE_METADATA_FRAGMENTS = (
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if len(value) > 32:
        raise ValueError("organization structure metadata has too many properties")
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = key.strip()
        if (
            not METADATA_KEY_PATTERN.fullmatch(normalized_key)
            or any(fragment in normalized_key.casefold() for fragment in SENSITIVE_METADATA_FRAGMENTS)
        ):
            raise ValueError("organization structure metadata key is not allowed")
        if item is not None and not isinstance(item, str | int | float | bool):
            raise ValueError("organization structure metadata values must be scalar")
        if isinstance(item, str) and len(item) > 1024:
            raise ValueError("organization structure metadata value is too long")
        result[normalized_key] = item
    return result


class OrganizationStructureNodeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=160)
    node_id: uuid.UUID | None = None
    intent: Literal["create", "retain", "update", "archive", "restore"]
    node_type: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=dict)

    @field_validator("ref")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NODE_REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("organization structure node reference is invalid")
        return normalized

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _safe_metadata(value)

    @field_validator("position")
    @classmethod
    def validate_position(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) - {"x", "y"}:
            raise ValueError("organization structure position contains unknown properties")
        result: dict[str, float] = {}
        for key, item in value.items():
            number = float(item)
            if not -100000 <= number <= 100000:
                raise ValueError("organization structure position is outside supported bounds")
            result[key] = number
        return result

    @model_validator(mode="after")
    def validate_identity(self) -> OrganizationStructureNodeProposal:
        if self.intent == "create":
            if self.node_id is not None or not self.ref.startswith("local:"):
                raise ValueError("new organization structure nodes require a local reference")
        elif self.node_id is None or self.ref != str(self.node_id):
            raise ValueError("persisted organization structure node identity is inconsistent")
        return self


class OrganizationStructureHierarchyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_ref: str = Field(min_length=1, max_length=160)
    child_ref: str = Field(min_length=1, max_length=160)

    @field_validator("parent_ref", "child_ref")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NODE_REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("organization structure hierarchy reference is invalid")
        return normalized


class OrganizationStructureRelationshipProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: uuid.UUID | None = None
    source_ref: str = Field(min_length=1, max_length=160)
    target_ref: str = Field(min_length=1, max_length=160)
    relationship_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    intent: Literal["create", "retain", "archive", "restore"] = "retain"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ref", "target_ref")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NODE_REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("organization structure relationship reference is invalid")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _safe_metadata(value)


class OrganizationStructureSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    mutation_key: uuid.UUID
    nodes: list[OrganizationStructureNodeProposal] = Field(max_length=1000)
    hierarchy: list[OrganizationStructureHierarchyProposal] = Field(max_length=1000)
    additional_relationships: list[OrganizationStructureRelationshipProposal] = Field(
        default_factory=list,
        max_length=2000,
    )
    normalize_legacy_contains: bool = False


class OrganizationStructureConvergenceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: uuid.UUID
    target_node_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )


class OrganizationStructureConvergencePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[OrganizationStructureConvergenceTarget] = Field(
        default_factory=list,
        max_length=1000,
    )
    normalize_legacy_contains: bool = True

    @model_validator(mode="after")
    def validate_unique_targets(
        self,
    ) -> OrganizationStructureConvergencePreviewRequest:
        node_ids = [item.node_id for item in self.targets]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("organization structure convergence targets must be unique")
        return self


class OrganizationStructureConvergenceApplyRequest(
    OrganizationStructureConvergencePreviewRequest
):
    expected_revision: int = Field(ge=0)
    mutation_key: uuid.UUID
    preview_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class OrganizationStructureConvergencePreviewResponse(BaseModel):
    organization_structure_convergence_schema_version: str = "1"
    source_revision: int
    preview_hash: str
    ready: bool
    nodes: list[dict[str, Any]]
    hierarchy_changes: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    impact: dict[str, Any]
    capabilities: dict[str, bool]
    postgresql_source_of_truth: bool = True
    generated_at: datetime


class OrganizationStructureRuntimeResponse(BaseModel):
    organization_structure_schema_version: str = "1"
    organization: dict[str, Any]
    revision: int
    root_policy: Literal["multiple"]
    capabilities: dict[str, bool]
    node_type_catalog: list[dict[str, Any]]
    relationship_type_catalog: list[dict[str, Any]]
    nodes: list[dict[str, Any]]
    hierarchy: list[dict[str, Any]]
    additional_relationships: list[dict[str, Any]]
    legacy_relationships: list[dict[str, Any]]
    legacy_normalization_candidates: list[dict[str, Any]]
    legacy_warnings: list[dict[str, Any]]
    limits: dict[str, int]
    replayed: bool = False
    postgresql_source_of_truth: bool = True
    external_calls_performed: bool = False
    generated_at: datetime


class OrganizationStructureConvergenceApplyResponse(BaseModel):
    organization_structure_convergence_schema_version: str = "1"
    applied: bool
    replayed: bool
    previous_revision: int
    revision: int
    changes: list[dict[str, Any]]
    runtime: OrganizationStructureRuntimeResponse
    postgresql_source_of_truth: bool = True
