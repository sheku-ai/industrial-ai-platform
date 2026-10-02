from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.readiness import AuthoritativeReadinessEvidence


class RecoveryPolicyCreate(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    database_backup_enabled: bool = True
    object_storage_backup_enabled: bool = True
    configuration_backup_enabled: bool = True
    backup_frequency: str | None = None
    retention_days: int | None = Field(default=None, gt=0)
    retention_count: int | None = Field(default=None, gt=0)
    rpo_minutes: int | None = Field(default=None, gt=0)
    rto_minutes: int | None = Field(default=None, gt=0)
    verification_required: bool = True
    restore_test_frequency: str | None = None
    evidence_max_age_hours: int | None = Field(default=None, gt=0)
    provider_type: str = Field(default="external_evidence", max_length=64)
    provider_reference: str | None = Field(default=None, max_length=255)
    configuration_payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=255)


class RecoveryPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    database_backup_enabled: bool | None = None
    object_storage_backup_enabled: bool | None = None
    configuration_backup_enabled: bool | None = None
    backup_frequency: str | None = None
    retention_days: int | None = Field(default=None, gt=0)
    retention_count: int | None = Field(default=None, gt=0)
    rpo_minutes: int | None = Field(default=None, gt=0)
    rto_minutes: int | None = Field(default=None, gt=0)
    verification_required: bool | None = None
    restore_test_frequency: str | None = None
    evidence_max_age_hours: int | None = Field(default=None, gt=0)
    provider_type: str | None = Field(default=None, max_length=64)
    provider_reference: str | None = Field(default=None, max_length=255)
    configuration_payload: dict[str, Any] | None = None


class RecoveryPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    name: str
    description: str | None = None
    status: str
    database_backup_enabled: bool
    object_storage_backup_enabled: bool
    configuration_backup_enabled: bool
    backup_frequency: str | None = None
    retention_days: int | None = None
    retention_count: int | None = None
    rpo_minutes: int | None = None
    rto_minutes: int | None = None
    verification_required: bool
    restore_test_frequency: str | None = None
    evidence_max_age_hours: int | None = None
    provider_type: str
    provider_reference: str | None = None
    configuration_payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    deactivated_at: datetime | None = None


class BackupExecutionCreate(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    policy_id: uuid.UUID
    provider_type: str = Field(default="external_evidence", max_length=64)
    provider_execution_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    requested_by: str | None = None
    backup_type: str = Field(default="external", pattern="^(full|incremental|differential|snapshot|external)$")
    database_included: bool = False
    object_storage_included: bool = False
    configuration_included: bool = False
    consistent_snapshot: bool = False
    manifest_hash: str | None = None
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)


class BackupExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    policy_id: uuid.UUID
    provider_type: str
    provider_execution_id: str | None = None
    correlation_id: str
    idempotency_key: str
    requested_by: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str
    backup_type: str
    database_included: bool
    object_storage_included: bool
    configuration_included: bool
    consistent_snapshot: bool
    artifact_count: int
    total_size_bytes: int | None = None
    manifest_hash: str | None = None
    input_hash: str
    result_hash: str | None = None
    failure_code: str | None = None
    failure_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class BackupArtifactCreate(BaseModel):
    artifact_type: str = Field(max_length=128)
    resource_type: str = Field(
        pattern="^(postgresql|platform_postgresql|identity_postgresql|object_storage|application_configuration|migration_manifest|release_manifest|other)$"
    )
    provider_reference: str | None = None
    storage_location: str | None = None
    storage_location_masked: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_algorithm: str | None = None
    checksum: str | None = None
    encryption_status: str | None = None
    compression_status: str | None = None
    created_at_source: datetime | None = None
    observed_at: datetime | None = None
    verified_at: datetime | None = None
    verification_status: str = Field(default="pending", pattern="^(pending|verified|failed|not_supported)$")
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class BackupArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    backup_execution_id: uuid.UUID
    artifact_type: str
    resource_type: str
    provider_reference: str | None = None
    storage_location_masked: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum: str | None = None
    encryption_status: str | None = None
    compression_status: str | None = None
    created_at_source: datetime | None = None
    observed_at: datetime | None = None
    verified_at: datetime | None = None
    verification_status: str
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class BackupCompleteRequest(BaseModel):
    provider_execution_id: str | None = None
    manifest_hash: str | None = None
    consistent_snapshot: bool | None = None


class RuntimeFailureRequest(BaseModel):
    failure_code: str = Field(min_length=1, max_length=128)
    failure_summary: str | None = None


class RestoreExecutionCreate(BaseModel):
    scope: str = Field(default="platform", pattern="^(platform|organization)$")
    organization_id: uuid.UUID | None = None
    policy_id: uuid.UUID
    backup_execution_id: uuid.UUID
    provider_type: str = Field(default="external_evidence", max_length=64)
    provider_execution_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    restore_target_type: str = Field(
        pattern="^(isolated_validation_environment|replacement_environment|existing_environment|external_target)$"
    )
    restore_target_reference: str | None = None
    requested_by: str | None = None
    destructive_operation: bool = False
    correlation_id: str | None = Field(default=None, max_length=128, exclude=True)


class RestoreExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    policy_id: uuid.UUID
    backup_execution_id: uuid.UUID
    provider_type: str
    provider_execution_id: str | None = None
    correlation_id: str
    idempotency_key: str
    restore_target_type: str
    restore_target_reference: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    requested_at: datetime
    approved_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str
    database_restored: bool
    object_storage_restored: bool
    configuration_restored: bool
    destructive_operation: bool
    input_hash: str
    result_hash: str | None = None
    failure_code: str | None = None
    failure_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class RestoreApproveRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=255)


class RestoreCompleteRequest(BaseModel):
    provider_execution_id: str | None = None
    database_restored: bool = False
    object_storage_restored: bool = False
    configuration_restored: bool = False


class RestoreVerificationCreate(BaseModel):
    verification_type: str = Field(default="external_evidence", max_length=128)
    verified_by: str | None = None


class RestoreVerificationCompleteRequest(BaseModel):
    database_connectivity_verified: bool = False
    schema_version_verified: bool = False
    record_counts_verified: bool = False
    object_storage_access_verified: bool = False
    artifact_checksums_verified: bool = False
    organization_isolation_verified: bool = False
    knowledge_lineage_verified: bool = False
    enterprise_search_verified: bool = False
    conversation_persistence_verified: bool = False
    document_registration_verified: bool = False
    assistant_runtime_verified: bool = False
    audit_runtime_verified: bool = False
    verification_payload: dict[str, Any] = Field(default_factory=dict)
    verified_by: str | None = None


class RestoreVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restore_execution_id: uuid.UUID
    verification_type: str
    status: str
    database_connectivity_verified: bool
    schema_version_verified: bool
    record_counts_verified: bool
    object_storage_access_verified: bool
    artifact_checksums_verified: bool
    organization_isolation_verified: bool
    knowledge_lineage_verified: bool
    enterprise_search_verified: bool
    conversation_persistence_verified: bool
    document_registration_verified: bool
    assistant_runtime_verified: bool
    audit_runtime_verified: bool
    verification_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: str | None = None
    verified_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RecoveryEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    scope: str
    evidence_type: str
    source_entity_type: str
    source_entity_id: str
    status: str
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: str
    observed_at: datetime
    expires_at: datetime | None = None
    created_at: datetime


class RecoveryReadinessGate(BaseModel):
    gate_code: str
    status: str
    summary: str
    evidence_reference: str | None = None
    blocker_code: str | None = None


class RecoveryReadinessResponse(BaseModel):
    evidence_contract: AuthoritativeReadinessEvidence
    scope: str
    organization_id: uuid.UUID | None = None
    status: str
    reason: str
    active_policy: RecoveryPolicyRead | None = None
    latest_backup: BackupExecutionRead | None = None
    latest_restore: RestoreExecutionRead | None = None
    latest_restore_verification: RestoreVerificationRead | None = None
    gates: list[RecoveryReadinessGate]
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    rpo: dict[str, Any] = Field(default_factory=dict)
    rto: dict[str, Any] = Field(default_factory=dict)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    evaluation_timestamp: datetime
    expires_at: datetime | None = None
    contract_version: str
    runtime_version: str
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False


class RecoveryWorkspaceRuntimeResponse(BaseModel):
    runtime_name: str = "recovery_workspace_runtime"
    runtime_status: str
    active_policy: RecoveryPolicyRead | None = None
    latest_backup: BackupExecutionRead | None = None
    latest_restore: RestoreExecutionRead | None = None
    latest_restore_verification: RestoreVerificationRead | None = None
    recovery_readiness: RecoveryReadinessResponse
    rpo: dict[str, Any] = Field(default_factory=dict)
    rto: dict[str, Any] = Field(default_factory=dict)
    evidence_freshness: dict[str, Any] = Field(default_factory=dict)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True
    side_effects_performed: bool = False
    external_calls_performed: bool = False
    llm_used: bool = False
    qdrant_used: bool = False
