from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.recovery import BackupExecution, RecoveryPolicy, RestoreExecution
from app.schemas.recovery import (
    BackupCompleteRequest,
    BackupExecutionRead,
    RestoreCompleteRequest,
    RestoreExecutionRead,
)
from app.services import recovery_runtime
from app.services.recovery_provider_execution_evidence import provider_execution_evidence_for
from app.services.recovery_resource_identity import (
    APPLICATION_CONFIGURATION,
    OBJECT_STORAGE,
    required_database_authorities,
)

complete_backup_execution_legacy = recovery_runtime.complete_backup_execution
complete_restore_execution_legacy = recovery_runtime.complete_restore_execution


def _required_resources(policy: RecoveryPolicy) -> tuple[str, ...]:
    resources = list(
        required_database_authorities(
            database_backup_enabled=policy.database_backup_enabled,
            scope=policy.scope,
        )
    )
    if policy.object_storage_backup_enabled:
        resources.append(OBJECT_STORAGE)
    if policy.configuration_backup_enabled:
        resources.append(APPLICATION_CONFIGURATION)
    return tuple(resources)


def _validated_provider_evidence(
    db: Session,
    *,
    policy: RecoveryPolicy,
    operation: str,
    execution: BackupExecution | RestoreExecution,
) -> tuple[dict[str, object], ...]:
    evidence_payloads: list[dict[str, object]] = []
    for resource_type in _required_resources(policy):
        evidence = provider_execution_evidence_for(
            db,
            scope=execution.scope,
            organization_id=execution.organization_id,
            operation=operation,
            execution_entity_id=execution.id,
            resource_type=resource_type,
        )
        if evidence is None:
            raise ValueError(f"{resource_type}_provider_execution_evidence_missing")
        payload = evidence.evidence_payload
        if payload.get("provider_type") != execution.provider_type:
            raise ValueError(f"{resource_type}_provider_execution_provider_mismatch")
        if payload.get("correlation_id") != execution.correlation_id:
            raise ValueError(f"{resource_type}_provider_execution_correlation_mismatch")
        if not payload.get("provider_execution_id"):
            raise ValueError(f"{resource_type}_provider_execution_id_missing")
        evidence_payloads.append(payload)
    return tuple(evidence_payloads)


def complete_backup_execution(
    db: Session,
    policy: RecoveryPolicy,
    backup: BackupExecution,
    payload: BackupCompleteRequest,
) -> BackupExecutionRead:
    provider_evidence = _validated_provider_evidence(
        db,
        policy=policy,
        operation="backup",
        execution=backup,
    )
    if payload.provider_execution_id:
        matching_ids = {str(item["provider_execution_id"]) for item in provider_evidence}
        if payload.provider_execution_id not in matching_ids:
            raise ValueError("backup_provider_execution_id_not_evidenced")
    return complete_backup_execution_legacy(db, policy, backup, payload)


def complete_restore_execution(
    db: Session,
    policy: RecoveryPolicy,
    restore: RestoreExecution,
    payload: RestoreCompleteRequest,
) -> RestoreExecutionRead:
    provider_evidence = _validated_provider_evidence(
        db,
        policy=policy,
        operation="restore",
        execution=restore,
    )
    resources = {str(item["resource_type"]) for item in provider_evidence}
    database_resources = set(
        required_database_authorities(
            database_backup_enabled=policy.database_backup_enabled,
            scope=policy.scope,
        )
    )
    authoritative_payload = payload.model_copy(
        update={
            "database_restored": (
                bool(database_resources) and database_resources.issubset(resources)
                if policy.database_backup_enabled
                else False
            ),
            "object_storage_restored": OBJECT_STORAGE in resources if policy.object_storage_backup_enabled else False,
            "configuration_restored": (
                APPLICATION_CONFIGURATION in resources if policy.configuration_backup_enabled else False
            ),
        }
    )
    if payload.provider_execution_id:
        matching_ids = {str(item["provider_execution_id"]) for item in provider_evidence}
        if payload.provider_execution_id not in matching_ids:
            raise ValueError("restore_provider_execution_id_not_evidenced")
    return complete_restore_execution_legacy(db, policy, restore, authoritative_payload)
