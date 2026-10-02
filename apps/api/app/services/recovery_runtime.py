from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.recovery import (
    BackupArtifactEvidence,
    BackupExecution,
    RecoveryEvidence,
    RecoveryPolicy,
    RestoreExecution,
    RestoreVerification,
)
from app.repositories.recovery import RecoveryRepository
from app.schemas.recovery import (
    BackupArtifactCreate,
    BackupArtifactRead,
    BackupCompleteRequest,
    BackupExecutionCreate,
    BackupExecutionRead,
    RecoveryPolicyCreate,
    RecoveryPolicyRead,
    RecoveryPolicyUpdate,
    RecoveryReadinessGate,
    RecoveryReadinessResponse,
    RecoveryWorkspaceRuntimeResponse,
    RestoreApproveRequest,
    RestoreCompleteRequest,
    RestoreExecutionCreate,
    RestoreExecutionRead,
    RestoreVerificationCompleteRequest,
    RestoreVerificationCreate,
    RestoreVerificationRead,
    RuntimeFailureRequest,
)
from app.services.readiness_contract import build_readiness_evidence
from app.services.recovery_provider_contracts import (
    BackupProviderRequest,
    RestoreProviderRequest,
    get_recovery_provider,
)
from app.services.recovery_resource_identity import (
    APPLICATION_CONFIGURATION,
    OBJECT_STORAGE,
    PLATFORM_POSTGRESQL,
    required_database_authorities,
)

RECOVERY_GATE_ORDER = (
    "backup_policy_configured",
    "latest_backup_evidence_available",
    "latest_restore_verification_available",
    "rpo_configured",
    "rto_configured",
    "object_storage_recovery_defined",
    "database_recovery_defined",
    "recovery_evidence_fresh",
)
BLOCKERS = {
    "backup_policy_configured": "BACKUP_POLICY_NOT_CONFIGURED",
    "latest_backup_evidence_available": "LATEST_BACKUP_EVIDENCE_MISSING",
    "latest_restore_verification_available": "LATEST_RESTORE_VERIFICATION_MISSING",
    "rpo_configured": "RPO_NOT_CONFIGURED",
    "rto_configured": "RTO_NOT_CONFIGURED",
    "object_storage_recovery_defined": "OBJECT_STORAGE_RECOVERY_NOT_DEFINED",
    "database_recovery_defined": "DATABASE_RECOVERY_NOT_DEFINED",
    "recovery_evidence_fresh": "RECOVERY_EVIDENCE_NOT_FRESH",
}
NEXT_ACTIONS = {
    "backup_policy_configured": "create_recovery_policy",
    "latest_backup_evidence_available": "register_backup",
    "latest_restore_verification_available": "complete_restore_verification",
    "rpo_configured": "configure_rpo",
    "rto_configured": "configure_rto",
    "object_storage_recovery_defined": "add_object_storage_artifact",
    "database_recovery_defined": "add_database_artifact",
    "recovery_evidence_fresh": "refresh_recovery_evidence",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_json(item) for item in value]
    return value


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_safe_json(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def mask_storage_location(value: str | None) -> str | None:
    if not value:
        return None
    sanitized = re.sub(r"://([^/\s:]+):([^@\s]+)@", r"://********:********@", value)
    if any(token in sanitized.lower() for token in ("secret", "password", "token", "access_key")):
        return "configured"
    if len(sanitized) > 128:
        return f"{sanitized[:48]}...{sanitized[-24:]}"
    return sanitized


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(token in lowered for token in ("password", "secret", "token", "access_key", "connection")):
            sanitized[key] = "configured"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_payload(item) if isinstance(item, dict) else item for item in value]
        else:
            sanitized[key] = value
    return sanitized


def _normalize_scope(scope: str, organization_id: uuid.UUID | None) -> tuple[str, uuid.UUID | None]:
    if scope == "platform":
        return "platform", None
    if organization_id is None:
        raise ValueError("organization_id_required")
    return "organization", organization_id


def _policy_read(policy: RecoveryPolicy | None) -> RecoveryPolicyRead | None:
    return RecoveryPolicyRead.model_validate(policy) if policy else None


def _backup_read(backup: BackupExecution | None) -> BackupExecutionRead | None:
    return BackupExecutionRead.model_validate(backup) if backup else None


def _restore_read(restore: RestoreExecution | None) -> RestoreExecutionRead | None:
    return RestoreExecutionRead.model_validate(restore) if restore else None


def _verification_read(verification: RestoreVerification | None) -> RestoreVerificationRead | None:
    return RestoreVerificationRead.model_validate(verification) if verification else None


def create_recovery_policy(db: Session, payload: RecoveryPolicyCreate) -> RecoveryPolicyRead:
    scope, organization_id = _normalize_scope(payload.scope, payload.organization_id)
    policy = RecoveryPolicy(
        organization_id=organization_id,
        scope=scope,
        name=payload.name,
        description=payload.description,
        status="draft",
        database_backup_enabled=payload.database_backup_enabled,
        object_storage_backup_enabled=payload.object_storage_backup_enabled,
        configuration_backup_enabled=payload.configuration_backup_enabled,
        backup_frequency=payload.backup_frequency,
        retention_days=payload.retention_days,
        retention_count=payload.retention_count,
        rpo_minutes=payload.rpo_minutes,
        rto_minutes=payload.rto_minutes,
        verification_required=payload.verification_required,
        restore_test_frequency=payload.restore_test_frequency,
        evidence_max_age_hours=payload.evidence_max_age_hours,
        provider_type=payload.provider_type,
        provider_reference=payload.provider_reference,
        configuration_payload=_sanitize_payload(payload.configuration_payload),
        created_by=payload.created_by,
    )
    db.add(policy)
    db.flush()
    return RecoveryPolicyRead.model_validate(policy)


def update_recovery_policy(db: Session, policy: RecoveryPolicy, payload: RecoveryPolicyUpdate) -> RecoveryPolicyRead:
    updates = payload.model_dump(exclude_unset=True)
    if "configuration_payload" in updates and updates["configuration_payload"] is not None:
        updates["configuration_payload"] = _sanitize_payload(updates["configuration_payload"])
    for key, value in updates.items():
        setattr(policy, key, value)
    db.flush()
    return RecoveryPolicyRead.model_validate(policy)


def activate_recovery_policy(db: Session, policy: RecoveryPolicy) -> RecoveryPolicyRead:
    repo = RecoveryRepository(db)
    locked_policies = repo.policies_for_activation(
        scope=policy.scope,
        organization_id=policy.organization_id,
        policy_id=policy.id,
    )
    target = next((item for item in locked_policies if item.id == policy.id), None)
    if target is None:
        raise ValueError("recovery_policy_not_found")
    if target.status == "active":
        return RecoveryPolicyRead.model_validate(target)
    now = _utcnow()
    try:
        for item in locked_policies:
            if item.id != target.id and item.status == "active":
                item.status = "inactive"
                item.deactivated_at = now
                db.add(item)
        db.flush()
        target.status = "active"
        target.activated_at = now
        target.deactivated_at = None
        db.add(target)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("recovery_policy_activation_conflict") from exc
    return RecoveryPolicyRead.model_validate(target)


def deactivate_recovery_policy(db: Session, policy: RecoveryPolicy) -> RecoveryPolicyRead:
    policy.status = "inactive"
    policy.deactivated_at = _utcnow()
    db.flush()
    return RecoveryPolicyRead.model_validate(policy)


def register_backup_execution(db: Session, payload: BackupExecutionCreate) -> BackupExecutionRead:
    scope, organization_id = _normalize_scope(payload.scope, payload.organization_id)
    repo = RecoveryRepository(db)
    policy = repo.get_policy(payload.policy_id, scope, organization_id)
    if policy is None:
        raise ValueError("recovery_policy_not_found")
    provider = get_recovery_provider(payload.provider_type)
    provider_result = provider.plan_backup(
        BackupProviderRequest(
            provider_type=payload.provider_type,
            provider_reference=policy.provider_reference,
            scope=scope,
            organization_id=str(organization_id) if organization_id else None,
            backup_type=payload.backup_type,
            configuration_payload=policy.configuration_payload,
        )
    )
    input_hash = stable_hash(
        {
            "scope": scope,
            "organization_id": organization_id,
            "policy_id": payload.policy_id,
            "backup_type": payload.backup_type,
            "database_included": payload.database_included,
            "object_storage_included": payload.object_storage_included,
            "configuration_included": payload.configuration_included,
            "manifest_hash": payload.manifest_hash,
        }
    )
    if repo.backup_idempotency_conflict(
        scope=scope,
        organization_id=organization_id,
        provider_type=payload.provider_type,
        input_hash=input_hash,
        idempotency_key=payload.idempotency_key,
    ):
        raise ValueError("idempotency_key_conflict")
    existing = repo.find_backup_by_idempotency(
        scope=scope,
        organization_id=organization_id,
        provider_type=payload.provider_type,
        input_hash=input_hash,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        return BackupExecutionRead.model_validate(existing)
    status = "blocked" if not provider_result.accepted else "running"
    backup = BackupExecution(
        organization_id=organization_id,
        scope=scope,
        policy_id=policy.id,
        provider_type=payload.provider_type,
        provider_execution_id=payload.provider_execution_id or provider_result.provider_execution_id,
        correlation_id=payload.correlation_id or f"backup:{uuid.uuid4()}",
        idempotency_key=payload.idempotency_key,
        requested_by=payload.requested_by,
        started_at=_utcnow() if status == "running" else None,
        status=status,
        backup_type=payload.backup_type,
        database_included=payload.database_included,
        object_storage_included=payload.object_storage_included,
        configuration_included=payload.configuration_included,
        consistent_snapshot=payload.consistent_snapshot,
        manifest_hash=payload.manifest_hash,
        input_hash=input_hash,
        failure_code="RECOVERY_PROVIDER_DISABLED" if status == "blocked" else None,
        failure_summary="Recovery provider is disabled." if status == "blocked" else None,
    )
    db.add(backup)
    db.flush()
    return BackupExecutionRead.model_validate(backup)


def add_backup_artifact(db: Session, backup: BackupExecution, payload: BackupArtifactCreate) -> BackupArtifactRead:
    artifact = BackupArtifactEvidence(
        backup_execution_id=backup.id,
        artifact_type=payload.artifact_type,
        resource_type=payload.resource_type,
        provider_reference=payload.provider_reference,
        storage_location_masked=payload.storage_location_masked or mask_storage_location(payload.storage_location),
        size_bytes=payload.size_bytes,
        checksum_algorithm=payload.checksum_algorithm,
        checksum=payload.checksum,
        encryption_status=payload.encryption_status,
        compression_status=payload.compression_status,
        created_at_source=payload.created_at_source,
        observed_at=payload.observed_at or _utcnow(),
        verified_at=payload.verified_at,
        verification_status=payload.verification_status,
        metadata_payload=_sanitize_payload(payload.metadata_payload),
    )
    db.add(artifact)
    db.flush()
    return BackupArtifactRead.model_validate(artifact)


def _required_resource_types(policy: RecoveryPolicy) -> set[str]:
    resources = set(
        required_database_authorities(
            database_backup_enabled=policy.database_backup_enabled,
            scope=policy.scope,
        )
    )
    if policy.object_storage_backup_enabled:
        resources.add(OBJECT_STORAGE)
    if policy.configuration_backup_enabled:
        resources.add(APPLICATION_CONFIGURATION)
    return resources


def _backup_completion_blockers(
    policy: RecoveryPolicy, backup: BackupExecution, artifacts: list[BackupArtifactEvidence]
) -> list[str]:
    blockers: list[str] = []
    if not backup.manifest_hash:
        blockers.append("BACKUP_MANIFEST_MISSING")
    if policy.database_backup_enabled and not backup.database_included:
        blockers.append("DATABASE_BACKUP_NOT_INCLUDED")
    if policy.object_storage_backup_enabled and not backup.object_storage_included:
        blockers.append("OBJECT_STORAGE_BACKUP_NOT_INCLUDED")
    if policy.configuration_backup_enabled and not backup.configuration_included:
        blockers.append("CONFIGURATION_BACKUP_NOT_INCLUDED")
    by_resource = {artifact.resource_type: artifact for artifact in artifacts}
    for resource_type in _required_resource_types(policy):
        artifact = by_resource.get(resource_type)
        if artifact is None:
            blockers.append(f"{resource_type.upper()}_ARTIFACT_MISSING")
        elif policy.verification_required and artifact.verification_status != "verified":
            blockers.append(f"{resource_type.upper()}_ARTIFACT_NOT_VERIFIED")
    metadata_by_resource = {artifact.resource_type: artifact.metadata_payload for artifact in artifacts}
    platform_database_metadata = metadata_by_resource.get(PLATFORM_POSTGRESQL, {})
    if not (
        metadata_by_resource.get("migration_manifest", {}).get("alembic_revision")
        or platform_database_metadata.get("alembic_revision")
    ):
        blockers.append("BACKUP_ALEMBIC_REVISION_MISSING")
    for database_authority in required_database_authorities(
        database_backup_enabled=policy.database_backup_enabled,
        scope=policy.scope,
    ):
        if not metadata_by_resource.get(database_authority, {}).get("postgresql_version"):
            blockers.append(f"{database_authority.upper()}_VERSION_MISSING")
    if not metadata_by_resource.get("release_manifest", {}).get("application_version"):
        blockers.append("BACKUP_APPLICATION_VERSION_MISSING")
    if not policy.evidence_max_age_hours:
        blockers.append("BACKUP_EVIDENCE_VALIDITY_MISSING")
    if not (backup.provider_execution_id or policy.provider_reference):
        blockers.append("BACKUP_PROVIDER_REFERENCE_MISSING")
    if backup.provider_type == "filesystem":
        for artifact in artifacts:
            if not artifact.provider_reference or not Path(artifact.provider_reference).is_file():
                blockers.append(f"{artifact.resource_type.upper()}_ARTIFACT_FILE_MISSING")
                continue
            if artifact.checksum_algorithm and artifact.checksum:
                if artifact.checksum_algorithm.lower() != "sha256":
                    blockers.append(f"{artifact.resource_type.upper()}_CHECKSUM_ALGORITHM_UNSUPPORTED")
                    continue
                digest = hashlib.sha256()
                with Path(artifact.provider_reference).open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != artifact.checksum.lower():
                    blockers.append(f"{artifact.resource_type.upper()}_CHECKSUM_MISMATCH")
    return blockers


def complete_backup_execution(
    db: Session,
    policy: RecoveryPolicy,
    backup: BackupExecution,
    payload: BackupCompleteRequest,
) -> BackupExecutionRead:
    if payload.provider_execution_id:
        backup.provider_execution_id = payload.provider_execution_id
    if payload.manifest_hash:
        backup.manifest_hash = payload.manifest_hash
    if payload.consistent_snapshot is not None:
        backup.consistent_snapshot = payload.consistent_snapshot
    artifacts = RecoveryRepository(db).artifacts_for_backup(backup.id)
    blockers = _backup_completion_blockers(policy, backup, artifacts)
    if blockers:
        backup.status = "blocked"
        backup.failure_code = blockers[0]
        backup.failure_summary = ", ".join(blockers)
    else:
        backup.status = "completed"
        backup.completed_at = _utcnow()
        backup.failure_code = None
        backup.failure_summary = None
    backup.artifact_count = len(artifacts)
    backup.total_size_bytes = sum(artifact.size_bytes or 0 for artifact in artifacts)
    backup.result_hash = stable_hash(
        {
            "backup_id": backup.id,
            "status": backup.status,
            "artifacts": [
                {
                    "id": artifact.id,
                    "resource_type": artifact.resource_type,
                    "verification_status": artifact.verification_status,
                    "checksum": artifact.checksum,
                }
                for artifact in artifacts
            ],
        }
    )
    db.flush()
    if backup.status == "completed":
        artifact_metadata = {
            artifact.resource_type: _sanitize_payload(artifact.metadata_payload) for artifact in artifacts
        }
        checksums = [
            {
                "artifact_id": str(artifact.id),
                "algorithm": artifact.checksum_algorithm,
                "checksum": artifact.checksum,
            }
            for artifact in artifacts
            if artifact.checksum_algorithm and artifact.checksum
        ]
        _upsert_recovery_evidence(
            db,
            scope=backup.scope,
            organization_id=backup.organization_id,
            evidence_type="backup_execution_completed",
            source_entity_type="backup_execution",
            source_entity_id=str(backup.id),
            status="passed",
            payload={
                "backup_id": str(backup.id),
                "scope": backup.scope,
                "organization_id": str(backup.organization_id) if backup.organization_id else None,
                "provider": backup.provider_type,
                "provider_reference": backup.provider_execution_id or policy.provider_reference,
                "started_at": backup.started_at,
                "completed_at": backup.completed_at,
                "status": "passed",
                "integrity_verified": all(artifact.verification_status == "verified" for artifact in artifacts),
                "checksums": checksums,
                "application_version": artifact_metadata.get("release_manifest", {}).get("application_version"),
                "alembic_revision": artifact_metadata.get("migration_manifest", {}).get("alembic_revision")
                or artifact_metadata.get(PLATFORM_POSTGRESQL, {}).get("alembic_revision"),
                "postgresql_version": artifact_metadata.get(PLATFORM_POSTGRESQL, {}).get("postgresql_version"),
                "database_authorities": {
                    authority: artifact_metadata.get(authority, {})
                    for authority in required_database_authorities(
                        database_backup_enabled=policy.database_backup_enabled,
                        scope=policy.scope,
                    )
                },
                "correlation_id": backup.correlation_id,
                "execution_key": backup.idempotency_key,
                "metadata": artifact_metadata,
                "error_code": None,
                "error_detail": None,
            },
            max_age_hours=policy.evidence_max_age_hours,
        )
        for artifact in artifacts:
            if artifact.verification_status == "verified":
                _upsert_recovery_evidence(
                    db,
                    scope=backup.scope,
                    organization_id=backup.organization_id,
                    evidence_type=f"{artifact.resource_type}_artifact_verified",
                    source_entity_type="backup_artifact",
                    source_entity_id=str(artifact.id),
                    status="passed",
                    payload={"backup_id": str(backup.id), "resource_type": artifact.resource_type},
                    max_age_hours=policy.evidence_max_age_hours,
                )
    return BackupExecutionRead.model_validate(backup)


def fail_backup_execution(db: Session, backup: BackupExecution, payload: RuntimeFailureRequest) -> BackupExecutionRead:
    backup.status = "failed"
    backup.completed_at = _utcnow()
    backup.failure_code = payload.failure_code
    backup.failure_summary = payload.failure_summary
    backup.result_hash = stable_hash(
        {"backup_id": backup.id, "status": backup.status, "failure_code": payload.failure_code}
    )
    db.flush()
    policy = RecoveryRepository(db).get_policy(backup.policy_id, backup.scope, backup.organization_id)
    _upsert_recovery_evidence(
        db,
        scope=backup.scope,
        organization_id=backup.organization_id,
        evidence_type="backup_execution_failed",
        source_entity_type="backup_execution",
        source_entity_id=str(backup.id),
        status="failed",
        payload={
            "backup_id": str(backup.id),
            "provider": backup.provider_type,
            "correlation_id": backup.correlation_id,
            "execution_key": backup.idempotency_key,
            "error_code": payload.failure_code,
            "error_detail": payload.failure_summary,
        },
        max_age_hours=policy.evidence_max_age_hours if policy else None,
    )
    return BackupExecutionRead.model_validate(backup)


def register_restore_execution(db: Session, payload: RestoreExecutionCreate) -> RestoreExecutionRead:
    scope, organization_id = _normalize_scope(payload.scope, payload.organization_id)
    repo = RecoveryRepository(db)
    policy = repo.get_policy(payload.policy_id, scope, organization_id)
    backup = repo.get_backup(payload.backup_execution_id, scope, organization_id)
    if policy is None or backup is None:
        raise ValueError("recovery_source_not_found")
    destructive = payload.destructive_operation or payload.restore_target_type == "existing_environment"
    provider = get_recovery_provider(payload.provider_type)
    provider_result = provider.plan_restore(
        RestoreProviderRequest(
            provider_type=payload.provider_type,
            provider_reference=policy.provider_reference,
            scope=scope,
            organization_id=str(organization_id) if organization_id else None,
            restore_target_type=payload.restore_target_type,
            restore_target_reference=payload.restore_target_reference,
            destructive_operation=destructive,
            configuration_payload=policy.configuration_payload,
        )
    )
    input_hash = stable_hash(
        {
            "scope": scope,
            "organization_id": organization_id,
            "policy_id": policy.id,
            "backup_execution_id": backup.id,
            "target_type": payload.restore_target_type,
            "target_reference": payload.restore_target_reference,
            "destructive_operation": destructive,
        }
    )
    if repo.restore_idempotency_conflict(
        scope=scope,
        organization_id=organization_id,
        provider_type=payload.provider_type,
        input_hash=input_hash,
        idempotency_key=payload.idempotency_key,
    ):
        raise ValueError("idempotency_key_conflict")
    existing = repo.find_restore_by_idempotency(
        scope=scope,
        organization_id=organization_id,
        provider_type=payload.provider_type,
        input_hash=input_hash,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        return RestoreExecutionRead.model_validate(existing)
    status = "blocked" if not provider_result.accepted else ("requested" if destructive else "running")
    restore = RestoreExecution(
        organization_id=organization_id,
        scope=scope,
        policy_id=policy.id,
        backup_execution_id=backup.id,
        provider_type=payload.provider_type,
        provider_execution_id=payload.provider_execution_id or provider_result.provider_execution_id,
        correlation_id=payload.correlation_id or f"restore:{uuid.uuid4()}",
        idempotency_key=payload.idempotency_key,
        restore_target_type=payload.restore_target_type,
        restore_target_reference=payload.restore_target_reference,
        requested_by=payload.requested_by,
        started_at=_utcnow() if status == "running" else None,
        status=status,
        destructive_operation=destructive,
        input_hash=input_hash,
        failure_code="RECOVERY_PROVIDER_DISABLED" if status == "blocked" else None,
        failure_summary="Recovery provider is disabled." if status == "blocked" else None,
    )
    db.add(restore)
    db.flush()
    return RestoreExecutionRead.model_validate(restore)


def approve_restore_execution(
    db: Session, restore: RestoreExecution, payload: RestoreApproveRequest
) -> RestoreExecutionRead:
    restore.status = "approved"
    restore.approved_by = payload.approved_by
    restore.approved_at = _utcnow()
    restore.started_at = restore.started_at or _utcnow()
    db.flush()
    return RestoreExecutionRead.model_validate(restore)


def complete_restore_execution(
    db: Session, policy: RecoveryPolicy, restore: RestoreExecution, payload: RestoreCompleteRequest
) -> RestoreExecutionRead:
    if restore.destructive_operation and not restore.approved_by:
        restore.status = "blocked"
        restore.failure_code = "DESTRUCTIVE_RESTORE_APPROVAL_REQUIRED"
        restore.failure_summary = "Destructive restore requires explicit approval."
        db.flush()
        return RestoreExecutionRead.model_validate(restore)
    if payload.provider_execution_id:
        restore.provider_execution_id = payload.provider_execution_id
    restore.database_restored = payload.database_restored
    restore.object_storage_restored = payload.object_storage_restored
    restore.configuration_restored = payload.configuration_restored
    blockers = []
    if policy.database_backup_enabled and not restore.database_restored:
        blockers.append("DATABASE_NOT_RESTORED")
    if policy.object_storage_backup_enabled and not restore.object_storage_restored:
        blockers.append("OBJECT_STORAGE_NOT_RESTORED")
    if policy.configuration_backup_enabled and not restore.configuration_restored:
        blockers.append("CONFIGURATION_NOT_RESTORED")
    if blockers:
        restore.status = "blocked"
        restore.failure_code = blockers[0]
        restore.failure_summary = ", ".join(blockers)
    else:
        restore.status = "completed"
        restore.completed_at = _utcnow()
        restore.failure_code = None
        restore.failure_summary = None
    restore.result_hash = stable_hash(
        {
            "restore_id": restore.id,
            "status": restore.status,
            "database_restored": restore.database_restored,
            "object_storage_restored": restore.object_storage_restored,
            "configuration_restored": restore.configuration_restored,
        }
    )
    db.flush()
    if restore.status == "completed":
        _upsert_recovery_evidence(
            db,
            scope=restore.scope,
            organization_id=restore.organization_id,
            evidence_type="restore_execution_completed",
            source_entity_type="restore_execution",
            source_entity_id=str(restore.id),
            status="passed",
            payload={"restore_id": str(restore.id), "backup_execution_id": str(restore.backup_execution_id)},
            max_age_hours=policy.evidence_max_age_hours,
        )
    return RestoreExecutionRead.model_validate(restore)


def fail_restore_execution(
    db: Session, restore: RestoreExecution, payload: RuntimeFailureRequest
) -> RestoreExecutionRead:
    restore.status = "failed"
    restore.completed_at = _utcnow()
    restore.failure_code = payload.failure_code
    restore.failure_summary = payload.failure_summary
    restore.result_hash = stable_hash(
        {"restore_id": restore.id, "status": restore.status, "failure_code": payload.failure_code}
    )
    db.flush()
    return RestoreExecutionRead.model_validate(restore)


def create_restore_verification(
    db: Session, restore: RestoreExecution, payload: RestoreVerificationCreate
) -> RestoreVerificationRead:
    verification = RestoreVerification(
        restore_execution_id=restore.id,
        verification_type=payload.verification_type,
        status="running",
        verified_by=payload.verified_by,
        started_at=_utcnow(),
    )
    db.add(verification)
    db.flush()
    return RestoreVerificationRead.model_validate(verification)


def _verification_passed(payload: RestoreVerificationCompleteRequest) -> bool:
    return all(
        (
            payload.database_connectivity_verified,
            payload.schema_version_verified,
            payload.record_counts_verified,
            payload.object_storage_access_verified,
            payload.artifact_checksums_verified,
            payload.organization_isolation_verified,
            payload.knowledge_lineage_verified,
            payload.enterprise_search_verified,
            payload.conversation_persistence_verified,
            payload.document_registration_verified,
            payload.assistant_runtime_verified,
            payload.audit_runtime_verified,
        )
    )


def complete_restore_verification(
    db: Session,
    policy: RecoveryPolicy,
    restore: RestoreExecution,
    verification: RestoreVerification,
    payload: RestoreVerificationCompleteRequest,
) -> RestoreVerificationRead:
    verification.database_connectivity_verified = payload.database_connectivity_verified
    verification.schema_version_verified = payload.schema_version_verified
    verification.record_counts_verified = payload.record_counts_verified
    verification.object_storage_access_verified = payload.object_storage_access_verified
    verification.artifact_checksums_verified = payload.artifact_checksums_verified
    verification.organization_isolation_verified = payload.organization_isolation_verified
    verification.knowledge_lineage_verified = payload.knowledge_lineage_verified
    verification.enterprise_search_verified = payload.enterprise_search_verified
    verification.conversation_persistence_verified = payload.conversation_persistence_verified
    verification.document_registration_verified = payload.document_registration_verified
    verification.assistant_runtime_verified = payload.assistant_runtime_verified
    verification.audit_runtime_verified = payload.audit_runtime_verified
    verification.verification_payload = _sanitize_payload(payload.verification_payload)
    verification.verified_by = payload.verified_by or verification.verified_by
    verification.completed_at = _utcnow()
    verification.status = "passed" if _verification_passed(payload) and restore.status == "completed" else "blocked"
    verification.evidence_hash = stable_hash(
        {
            "verification_id": verification.id,
            "restore_execution_id": restore.id,
            "status": verification.status,
            "payload": verification.verification_payload,
            "checks": {
                "database_connectivity_verified": verification.database_connectivity_verified,
                "schema_version_verified": verification.schema_version_verified,
                "record_counts_verified": verification.record_counts_verified,
                "object_storage_access_verified": verification.object_storage_access_verified,
                "artifact_checksums_verified": verification.artifact_checksums_verified,
                "organization_isolation_verified": verification.organization_isolation_verified,
                "knowledge_lineage_verified": verification.knowledge_lineage_verified,
                "enterprise_search_verified": verification.enterprise_search_verified,
                "conversation_persistence_verified": verification.conversation_persistence_verified,
                "document_registration_verified": verification.document_registration_verified,
                "assistant_runtime_verified": verification.assistant_runtime_verified,
                "audit_runtime_verified": verification.audit_runtime_verified,
            },
        }
    )
    db.flush()
    if verification.status == "passed":
        _upsert_recovery_evidence(
            db,
            scope=restore.scope,
            organization_id=restore.organization_id,
            evidence_type="restore_verification_passed",
            source_entity_type="restore_verification",
            source_entity_id=str(verification.id),
            status="passed",
            payload={"restore_id": str(restore.id), "verification_id": str(verification.id)},
            max_age_hours=policy.evidence_max_age_hours,
        )
    return RestoreVerificationRead.model_validate(verification)


def fail_restore_verification(
    db: Session, verification: RestoreVerification, payload: RuntimeFailureRequest
) -> RestoreVerificationRead:
    verification.status = "failed"
    verification.completed_at = _utcnow()
    verification.verification_payload = {
        "failure_code": payload.failure_code,
        "failure_summary": payload.failure_summary,
    }
    verification.evidence_hash = stable_hash(
        {"verification_id": verification.id, "status": "failed", "failure_code": payload.failure_code}
    )
    db.flush()
    return RestoreVerificationRead.model_validate(verification)


def _upsert_recovery_evidence(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    evidence_type: str,
    source_entity_type: str,
    source_entity_id: str,
    status: str,
    payload: dict[str, Any],
    max_age_hours: int | None,
) -> RecoveryEvidence:
    repo = RecoveryRepository(db)
    existing = next(
        (
            evidence
            for evidence in repo.latest_evidence(scope, organization_id)
            if evidence.evidence_type == evidence_type
            and evidence.source_entity_type == source_entity_type
            and evidence.source_entity_id == source_entity_id
        ),
        None,
    )
    observed_at = _utcnow()
    expires_at = observed_at + timedelta(hours=max_age_hours) if max_age_hours else None
    evidence_payload = _safe_json(_sanitize_payload(payload))
    evidence_hash = stable_hash(
        {
            "scope": scope,
            "organization_id": organization_id,
            "evidence_type": evidence_type,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "status": status,
            "payload": evidence_payload,
        }
    )
    evidence = existing or RecoveryEvidence(
        scope=scope,
        organization_id=organization_id,
        evidence_type=evidence_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
    )
    evidence.status = status
    evidence.evidence_payload = evidence_payload
    evidence.evidence_hash = evidence_hash
    evidence.observed_at = observed_at
    evidence.expires_at = expires_at
    if existing is None:
        db.add(evidence)
    db.flush()
    return evidence


def recovery_chain_correlated(
    policy: RecoveryPolicy | None,
    backup: BackupExecution | None,
    restore: RestoreExecution | None,
    verification: RestoreVerification | None,
) -> bool:
    return bool(
        policy
        and backup
        and restore
        and verification
        and backup.policy_id == policy.id
        and restore.policy_id == policy.id
        and backup.scope == policy.scope
        and restore.scope == policy.scope
        and backup.organization_id == policy.organization_id
        and restore.organization_id == policy.organization_id
        and restore.backup_execution_id == backup.id
        and verification.restore_execution_id == restore.id
    )


def recovery_evidence_freshness(
    policy: RecoveryPolicy | None,
    backup: BackupExecution | None,
    verification: RestoreVerification | None,
    now: datetime,
) -> tuple[bool, bool]:
    if policy is None or not policy.evidence_max_age_hours:
        return True, True
    max_age = timedelta(hours=policy.evidence_max_age_hours)
    backup_fresh = bool(backup and backup.completed_at and now - backup.completed_at <= max_age)
    verification_fresh = bool(verification and verification.completed_at and now - verification.completed_at <= max_age)
    return backup_fresh, verification_fresh


def physical_provider_execution_readiness(
    backup: BackupExecution | None,
    restore: RestoreExecution | None,
) -> dict[str, bool]:
    return {
        "backup_evidenced": bool(backup and backup.provider_execution_id),
        "restore_evidenced": bool(restore and restore.provider_execution_id),
        "required_by_recovery_control_plane": False,
    }


def build_recovery_readiness(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> RecoveryReadinessResponse:
    scope, organization_id = _normalize_scope(scope, organization_id)
    repo = RecoveryRepository(db)
    policy = repo.active_policy(scope, organization_id)
    latest_backup = repo.latest_completed_backup_for_policy(policy.id, scope, organization_id) if policy else None
    latest_restore = repo.latest_completed_restore_for_policy(policy.id, scope, organization_id) if policy else None
    latest_verification = repo.latest_passed_verification_for_restore(latest_restore.id) if latest_restore else None
    artifacts = repo.artifacts_for_backup(latest_backup.id) if latest_backup else []
    recovery_evidence_by_type: dict[str, RecoveryEvidence] = {}
    for item in repo.latest_evidence(scope, organization_id):
        recovery_evidence_by_type.setdefault(item.evidence_type, item)
    recovery_evidence = list(recovery_evidence_by_type.values())
    now = _utcnow()
    chain_correlated = recovery_chain_correlated(
        policy,
        latest_backup,
        latest_restore,
        latest_verification,
    )

    def gate(code: str, passed: bool, summary: str, evidence_reference: str | None = None) -> RecoveryReadinessGate:
        return RecoveryReadinessGate(
            gate_code=code,
            status="passed" if passed else "blocked",
            summary=summary,
            evidence_reference=evidence_reference,
            blocker_code=None if passed else BLOCKERS[code],
        )

    required = _required_resource_types(policy) if policy else set()
    by_resource = {artifact.resource_type: artifact for artifact in artifacts}
    backup_complete = bool(latest_backup and latest_backup.status == "completed")
    backup_resources_ok = bool(policy and latest_backup) and all(
        resource_type in by_resource
        and (not policy.verification_required or by_resource[resource_type].verification_status == "verified")
        for resource_type in required
    )
    database_resources = (
        required_database_authorities(database_backup_enabled=policy.database_backup_enabled, scope=policy.scope)
        if policy
        else ()
    )
    database_recovery_defined = bool(policy) and all(
        resource_type in by_resource
        and (not policy.verification_required or by_resource[resource_type].verification_status == "verified")
        for resource_type in database_resources
    )
    backup_fresh, restore_fresh = recovery_evidence_freshness(
        policy,
        latest_backup,
        latest_verification,
        now,
    )
    gates = [
        gate(
            "backup_policy_configured",
            policy is not None,
            "Active recovery policy exists.",
            str(policy.id) if policy else None,
        ),
        gate(
            "latest_backup_evidence_available",
            backup_complete and backup_resources_ok and backup_fresh,
            "Latest completed backup includes required verified artifacts.",
            str(latest_backup.id) if latest_backup else None,
        ),
        gate(
            "latest_restore_verification_available",
            latest_verification is not None and chain_correlated,
            "Latest restore verification passed.",
            str(latest_verification.id) if latest_verification else None,
        ),
        gate(
            "rpo_configured",
            bool(policy and policy.rpo_minutes),
            "RPO is configured.",
            str(policy.id) if policy else None,
        ),
        gate(
            "rto_configured",
            bool(policy and policy.rto_minutes),
            "RTO is configured.",
            str(policy.id) if policy else None,
        ),
        gate(
            "object_storage_recovery_defined",
            bool(
                policy
                and (
                    policy.object_storage_backup_enabled
                    or policy.configuration_payload.get("object_storage_exclusion_reason")
                )
            ),
            "Object storage recovery is defined or explicitly excluded.",
            str(policy.id) if policy else None,
        ),
        gate(
            "database_recovery_defined",
            database_recovery_defined,
            "Required PostgreSQL authorities have verified backup artifacts.",
            str(latest_backup.id) if latest_backup else None,
        ),
        gate(
            "recovery_evidence_fresh",
            bool(policy and backup_fresh and restore_fresh and latest_backup and latest_verification),
            "Backup and restore verification evidence are fresh.",
            str(latest_verification.id) if latest_verification else None,
        ),
    ]
    blockers = [
        {"code": item.blocker_code, "gate_code": item.gate_code, "message": item.summary}
        for item in gates
        if item.status == "blocked"
    ]
    next_actions = [
        {
            "action_key": NEXT_ACTIONS[item.gate_code],
            "gate_code": item.gate_code,
            "label": NEXT_ACTIONS[item.gate_code].replace("_", " ").capitalize(),
        }
        for item in gates
        if item.status == "blocked"
    ]
    status = "passed" if not blockers else "blocked"
    timestamps = [
        item
        for item in (
            latest_backup.completed_at if latest_backup else None,
            latest_verification.completed_at if latest_verification else None,
        )
        if item is not None
    ]
    expirations = (
        [item + timedelta(hours=policy.evidence_max_age_hours) for item in timestamps]
        if policy and policy.evidence_max_age_hours
        else []
    )
    stale = bool(policy and (latest_backup or latest_verification) and not (backup_fresh and restore_fresh))
    integrity_errors = [
        {
            "code": "recovery_evidence_corrupt",
            "message": "Persisted recovery evidence hash does not match its payload.",
            "evidence_id": str(item.id),
        }
        for item in recovery_evidence
        if stable_hash(
            {
                "scope": item.scope,
                "organization_id": item.organization_id,
                "evidence_type": item.evidence_type,
                "source_entity_type": item.source_entity_type,
                "source_entity_id": item.source_entity_id,
                "status": item.status,
                "payload": item.evidence_payload,
            }
        )
        != item.evidence_hash
    ]
    evidence_contract = build_readiness_evidence(
        domain="recovery",
        status="stale" if stale else status,
        gate_results=gates,
        blockers=blockers,
        warnings=[],
        next_actions=next_actions,
        runtime_version="recovery-evidence-runtime.v1",
        evaluation_timestamp=max(timestamps) if timestamps else None,
        expires_at=min(expirations) if expirations else None,
        evidence_origin="recovery_readiness_runtime",
        components_evaluated=["policy", "backup", "restore", "restore_verification"],
        evidence_ids=[
            *[str(item.id) for item in recovery_evidence],
            *[
                str(item.id)
                for item in (policy, latest_backup, latest_restore, latest_verification)
                if item is not None
            ],
        ],
        source_runtime_version="recovery-evidence-runtime.v1",
        supported_runtime_versions=("recovery-evidence-runtime.v1",),
        integrity_errors=integrity_errors,
    )
    return RecoveryReadinessResponse(
        evidence_contract=evidence_contract,
        scope=scope,
        organization_id=organization_id,
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        active_policy=_policy_read(policy),
        latest_backup=_backup_read(latest_backup),
        latest_restore=_restore_read(latest_restore),
        latest_restore_verification=_verification_read(latest_verification),
        gates=gates,
        blockers=evidence_contract.blockers,
        warnings=evidence_contract.warnings,
        recommendations=evidence_contract.recommendations,
        next_actions=evidence_contract.next_actions,
        rpo={"configured": bool(policy and policy.rpo_minutes), "minutes": policy.rpo_minutes if policy else None},
        rto={"configured": bool(policy and policy.rto_minutes), "minutes": policy.rto_minutes if policy else None},
        evidence_freshness={
            "configured_max_age_hours": policy.evidence_max_age_hours if policy else None,
            "backup_fresh": backup_fresh,
            "restore_verification_fresh": restore_fresh,
            "control_plane_evidence_ready": evidence_contract.status == "passed",
            "chain_correlated": chain_correlated,
            "physical_provider_execution": physical_provider_execution_readiness(
                latest_backup,
                latest_restore,
            ),
        },
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
        postgresql_source_of_truth=True,
        side_effects_performed=False,
        external_calls_performed=False,
        llm_used=False,
        qdrant_used=False,
    )


def build_recovery_workspace_runtime(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> RecoveryWorkspaceRuntimeResponse:
    readiness = build_recovery_readiness(db, scope=scope, organization_id=organization_id)
    return RecoveryWorkspaceRuntimeResponse(
        runtime_status=readiness.status,
        active_policy=readiness.active_policy,
        latest_backup=readiness.latest_backup,
        latest_restore=readiness.latest_restore,
        latest_restore_verification=readiness.latest_restore_verification,
        recovery_readiness=readiness,
        rpo=readiness.rpo,
        rto=readiness.rto,
        evidence_freshness=readiness.evidence_freshness,
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        next_actions=readiness.next_actions,
    )
