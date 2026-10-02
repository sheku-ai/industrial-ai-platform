from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.release_governance import (
    BuildManifestCreate,
    BuildManifestRead,
    Edition,
    GovernedReleaseRead,
    MigrationRequirementCreate,
    MigrationRequirementRead,
    ReleaseBuildRead,
    reject_secrets,
)


class BaselineReleaseLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_release_id: uuid.UUID
    migration: MigrationRequirementCreate
    provenance: dict[str, Any]

    @field_validator("provenance")
    @classmethod
    def validate_provenance(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("baseline lineage provenance is required")
        return reject_secrets(value)


class BaselineReleaseEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_version: str = Field(min_length=1, max_length=64)
    alembic_revision: str = Field(min_length=1, max_length=128)
    edition: Edition
    source_repository: str = Field(min_length=1, max_length=255)
    source_revision: str = Field(min_length=1, max_length=128)
    source_branch: str | None = Field(default=None, max_length=128)
    manifest: BuildManifestCreate
    lineage: BaselineReleaseLineage
    provenance: dict[str, Any]
    execution_key: str = Field(min_length=1, max_length=160)
    created_by: str | None = Field(default=None, max_length=255)

    @field_validator("provenance")
    @classmethod
    def validate_provenance(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("baseline provenance is required")
        return reject_secrets(value)

    @model_validator(mode="after")
    def validate_manifest_and_lineage(self) -> BaselineReleaseEvidenceCreate:
        if self.manifest.application_version != self.application_version:
            raise ValueError("baseline manifest application version mismatch")
        if self.manifest.database_schema_revision != self.alembic_revision:
            raise ValueError("baseline manifest Alembic revision mismatch")
        if self.manifest.source_revision != self.source_revision:
            raise ValueError("baseline manifest source revision mismatch")
        if self.lineage.migration.from_revision != self.alembic_revision:
            raise ValueError("baseline lineage source revision mismatch")
        return self


class BaselineReleaseEvidenceContract(BaseModel):
    contract_version: Literal["baseline_release_evidence.v1"] = "baseline_release_evidence.v1"
    evidence_origin: Literal["postgresql_release_governance"] = "postgresql_release_governance"
    execution_key: str
    input_hash: str
    application_version: str
    alembic_revision: str
    edition: Edition
    release_id: uuid.UUID
    build_id: uuid.UUID
    manifest_id: uuid.UUID
    target_release_id: uuid.UUID
    migration_requirement_id: uuid.UUID
    provenance: dict[str, Any]
    lineage: BaselineReleaseLineage
    created_at: datetime


class BaselineReleaseEvidenceRead(BaseModel):
    baseline_release_evidence: BaselineReleaseEvidenceContract
    backup_evidence_available: Literal[False] = False
    recovery_ready: Literal[False] = False
    upgrade_governance_ready: bool
    application_version: str
    alembic_revision: str
    edition: Edition
    execution_key: str
    reused: bool
    release: GovernedReleaseRead
    build: ReleaseBuildRead
    manifest: BuildManifestRead
    migration_requirement: MigrationRequirementRead
    created_at: datetime
