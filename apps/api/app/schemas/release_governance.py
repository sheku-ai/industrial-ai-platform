from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.readiness import AuthoritativeReadinessEvidence

Edition = Literal["community", "enterprise"]
ReleaseChannel = Literal["development", "acceptance", "release_candidate", "stable"]
ReleaseStatus = Literal[
    "draft", "assembling", "ready_for_validation", "validated", "approved", "superseded", "retired", "blocked"
]


def mask_artifact_location(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    return re.sub(r"(?i)(token|secret|password|access_key)=([^&\s]+)", r"\1=***", value)


def reject_credential_reference(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise ValueError("references containing credentials are not accepted")
    if re.search(r"(?i)(token|secret|password|access_key)=", value):
        raise ValueError("references containing credentials are not accepted")
    return value


def reject_secrets(value: Any) -> Any:
    secret_names = {"password", "secret", "token", "access_key", "secret_key", "private_key", "credential"}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in secret_names:
                    raise ValueError("secret material is not accepted")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return value


class GovernedReleaseCreate(BaseModel):
    release_code: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    edition: Edition
    channel: ReleaseChannel
    source_repository: str = Field(min_length=1, max_length=255)
    source_revision: str = Field(min_length=1, max_length=128)
    source_branch: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    created_by: str | None = Field(default=None, max_length=255)

    _safe_repository = field_validator("source_repository")(reject_credential_reference)


class GovernedReleaseUpdate(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=64)
    channel: ReleaseChannel | None = None
    status: ReleaseStatus | None = None
    source_branch: str | None = Field(default=None, max_length=128)


class GovernedReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_code: str
    version: str
    edition: Edition
    channel: ReleaseChannel
    status: ReleaseStatus
    source_repository: str
    source_revision: str
    source_branch: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    prepared_at: datetime | None = None
    approved_at: datetime | None = None
    retired_at: datetime | None = None
    contract_version: str
    idempotency_key: str
    input_hash: str
    result_hash: str | None = None


class ReleaseBuildCreate(BaseModel):
    build_number: str = Field(min_length=1, max_length=64)
    build_timestamp: datetime
    builder_type: Literal["local", "ci", "external", "manual_evidence"]
    builder_reference: str | None = Field(default=None, max_length=255)
    source_revision: str = Field(min_length=1, max_length=128)
    target_platform: Literal["linux", "darwin", "windows", "container", "other"]
    target_architecture: Literal["amd64", "arm64", "multi_arch", "other"]
    build_profile: str = Field(min_length=1, max_length=128)
    reproducibility_evidence: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)

    _reject_secrets = field_validator("reproducibility_evidence")(reject_secrets)


class ReleaseBuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    build_number: str
    build_status: str
    build_timestamp: datetime
    builder_type: str
    builder_reference: str | None = None
    source_revision: str
    target_platform: str
    target_architecture: str
    build_profile: str
    reproducible: bool
    reproducibility_evidence: dict[str, Any]
    input_hash: str
    result_hash: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReleaseBuildComplete(BaseModel):
    reproducibility_evidence: dict[str, Any] = Field(default_factory=dict)
    result_evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reproducibility_evidence", "result_evidence")
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)


class BuildManifestCreate(BaseModel):
    manifest_version: str = Field(min_length=1, max_length=64)
    application_version: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=128)
    build_timestamp: datetime
    python_version: str | None = Field(default=None, max_length=64)
    node_version: str | None = Field(default=None, max_length=64)
    database_schema_revision: str = Field(min_length=1, max_length=128)
    container_runtime: str | None = Field(default=None, max_length=128)
    target_platforms: list[str] = Field(min_length=1)
    target_architectures: list[str] = Field(min_length=1)
    dependency_summary: dict[str, Any] = Field(default_factory=dict)
    component_versions: dict[str, Any]
    configuration_profile: str = Field(min_length=1, max_length=128)
    manifest_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dependency_summary", "component_versions", "manifest_payload")
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)

    @model_validator(mode="after")
    def required_components(self) -> BuildManifestCreate:
        required = {
            "api",
            "portal",
            "workers",
            "scheduler",
            "migrator",
            "object_storage_integration",
            "database_compatibility",
        }
        missing = sorted(required - set(self.component_versions))
        if missing:
            raise ValueError(f"required component versions missing: {', '.join(missing)}")
        return self


class BuildManifestRead(BuildManifestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    build_id: uuid.UUID
    manifest_hash: str
    created_at: datetime


class DeploymentManifestCreate(BaseModel):
    build_id: uuid.UUID
    manifest_version: str = Field(min_length=1, max_length=64)
    deployment_profile: Literal["local", "on_premise", "hybrid", "cloud"]
    deployment_strategy: Literal["recreate", "rolling", "blue_green", "external"]
    required_services: list[str] = Field(min_length=1)
    optional_services: list[str] = Field(default_factory=list)
    health_checks: list[dict[str, Any]] = Field(min_length=1)
    readiness_checks: list[dict[str, Any]] = Field(min_length=1)
    startup_order: list[str] = Field(min_length=1)
    configuration_requirements: dict[str, Any]
    secret_requirements: list[str] = Field(default_factory=list)
    storage_requirements: dict[str, Any]
    network_requirements: dict[str, Any]
    resource_requirements: dict[str, Any]
    migration_requirements: dict[str, Any]
    rollback_target_release_id: uuid.UUID | None = None
    rollback_procedure_reference: str | None = Field(default=None, max_length=255)
    manifest_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "health_checks",
        "readiness_checks",
        "configuration_requirements",
        "storage_requirements",
        "network_requirements",
        "resource_requirements",
        "migration_requirements",
        "manifest_payload",
    )
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)


class DeploymentManifestRead(DeploymentManifestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    manifest_hash: str
    created_at: datetime
    updated_at: datetime


class ReleaseArtifactCreate(BaseModel):
    build_id: uuid.UUID
    artifact_code: str = Field(min_length=1, max_length=128)
    artifact_type: Literal[
        "container_image",
        "source_bundle",
        "portal_bundle",
        "python_package",
        "migration_bundle",
        "configuration_template",
        "sbom",
        "signature",
        "provenance",
        "release_notes",
        "compatibility_manifest",
        "deployment_manifest",
        "other",
    ]
    component: str = Field(min_length=1, max_length=128)
    edition: Edition
    platform: str = Field(min_length=1, max_length=32)
    architecture: str = Field(min_length=1, max_length=32)
    media_type: str = Field(min_length=1, max_length=255)
    artifact_reference: str = Field(min_length=1, max_length=512)
    artifact_location: str | None = Field(default=None, max_length=1024, exclude=True)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_algorithm: str | None = Field(default=None, max_length=32)
    checksum: str | None = Field(default=None, max_length=256)
    digest_algorithm: str | None = Field(default=None, max_length=32)
    digest: str | None = Field(default=None, max_length=256)
    signature_status: Literal["not_provided", "pending", "verified", "failed", "not_applicable"] = "not_provided"
    provenance_status: Literal["not_provided", "pending", "verified", "failed"] = "not_provided"
    sbom_status: Literal["not_provided", "pending", "available", "verified", "failed"] = "not_provided"
    required: bool = True
    metadata_payload: dict[str, Any] = Field(default_factory=dict)

    _reject_secrets = field_validator("metadata_payload")(reject_secrets)
    _safe_reference = field_validator("artifact_reference")(reject_credential_reference)

    @model_validator(mode="after")
    def required_identity(self) -> ReleaseArtifactCreate:
        if (
            self.required
            and not (self.checksum and self.checksum_algorithm)
            and not (self.digest and self.digest_algorithm)
        ):
            raise ValueError("required artifacts need checksum or digest evidence")
        return self


class ReleaseArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    build_id: uuid.UUID
    artifact_code: str
    artifact_type: str
    component: str
    edition: Edition
    platform: str
    architecture: str
    media_type: str
    artifact_reference: str
    artifact_location_masked: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum: str | None = None
    digest_algorithm: str | None = None
    digest: str | None = None
    signature_status: str
    provenance_status: str
    sbom_status: str
    required: bool
    status: str
    metadata_payload: dict[str, Any]
    created_at: datetime
    verified_at: datetime | None = None


class ReleaseArtifactVerify(BaseModel):
    checksum_verified: bool
    digest_verified: bool
    provenance_status: Literal["not_provided", "pending", "verified", "failed"]
    sbom_status: Literal["not_provided", "pending", "available", "verified", "failed"]
    signature_status: Literal["not_provided", "pending", "verified", "failed", "not_applicable"] = "not_provided"
    evidence_payload: dict[str, Any]

    _reject_secrets = field_validator("evidence_payload")(reject_secrets)

    @field_validator("evidence_payload")
    @classmethod
    def evidence_required(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("artifact verification evidence is required")
        return value


class ReleaseCompatibilityCreate(BaseModel):
    compatibility_type: Literal[
        "database_schema",
        "previous_release",
        "postgresql",
        "redis",
        "object_storage",
        "python",
        "node",
        "browser",
        "operating_system",
        "container_runtime",
        "other",
    ]
    minimum_version: str | None = Field(default=None, max_length=128)
    maximum_version: str | None = Field(default=None, max_length=128)
    compatible: bool
    requirements: dict[str, Any] = Field(default_factory=dict)
    evidence_payload: dict[str, Any]

    @field_validator("requirements", "evidence_payload")
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)

    @field_validator("evidence_payload")
    @classmethod
    def evidence_required(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("compatibility evidence is required")
        return value


class ReleaseCompatibilityRead(ReleaseCompatibilityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    evidence_hash: str
    created_at: datetime


class MigrationRequirementCreate(BaseModel):
    from_revision: str | None = Field(default=None, max_length=128)
    to_revision: str = Field(min_length=1, max_length=128)
    migration_required: bool
    migration_strategy: Literal["none", "forward_only", "expand_contract", "offline", "external"]
    reversible: bool
    irreversible_reason: str | None = None
    preconditions: list[dict[str, Any]] = Field(default_factory=list)
    postconditions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_payload: dict[str, Any]

    @field_validator("preconditions", "postconditions", "evidence_payload")
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)

    @model_validator(mode="after")
    def irreversible_evidence(self) -> MigrationRequirementCreate:
        if not self.reversible and not self.irreversible_reason:
            raise ValueError("irreversible migration requires a reason")
        if not self.migration_required and self.migration_strategy != "none":
            raise ValueError("migration strategy must be none when no migration is required")
        return self

    @field_validator("evidence_payload")
    @classmethod
    def evidence_required(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("migration evidence is required")
        return value


class MigrationRequirementRead(MigrationRequirementCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    evidence_hash: str
    created_at: datetime


class RollbackTargetCreate(BaseModel):
    rollback_target_release_id: uuid.UUID
    rollback_supported: bool
    rollback_strategy: str = Field(min_length=1, max_length=64)
    database_rollback_supported: bool
    application_rollback_supported: bool
    required_actions: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    evidence_payload: dict[str, Any]
    verified_at: datetime | None = None

    @field_validator("required_actions", "blockers", "evidence_payload")
    @classmethod
    def no_secrets(cls, value: Any) -> Any:
        return reject_secrets(value)

    @field_validator("evidence_payload")
    @classmethod
    def evidence_required(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("rollback evidence is required")
        return value


class RollbackTargetRead(RollbackTargetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    evidence_hash: str


class ReleaseAcceptanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    status: str
    build_manifest_valid: bool
    deployment_manifest_valid: bool
    required_artifacts_present: bool
    required_artifacts_verified: bool
    checksums_valid: bool
    digests_valid: bool
    provenance_available: bool
    sbom_available: bool
    compatibility_valid: bool
    migration_requirements_valid: bool
    rollback_target_valid: bool
    edition_boundary_valid: bool
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    evidence_payload: dict[str, Any]
    evidence_hash: str
    result_hash: str
    evaluated_at: datetime
    created_at: datetime


class ReleaseReadinessResponse(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    status: str
    reason: str
    release: GovernedReleaseRead
    build: ReleaseBuildRead | None = None
    build_manifest: BuildManifestRead | None = None
    deployment_manifest: DeploymentManifestRead | None = None
    artifact_summary: dict[str, Any]
    artifacts: list[ReleaseArtifactRead]
    compatibility_summary: dict[str, Any]
    migration_summary: dict[str, Any]
    rollback_summary: dict[str, Any]
    acceptance: ReleaseAcceptanceRead | None = None
    acceptance_status: str
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    contract_version: str
    runtime_version: str
    postgresql_source_of_truth: bool = True
    llm_used: bool = False
    qdrant_used: bool = False


class LatestReleaseResponse(BaseModel):
    found: bool
    release: GovernedReleaseRead | None = None


class LatestReleaseReadinessResponse(BaseModel):
    found: bool
    readiness: ReleaseReadinessResponse | None = None
