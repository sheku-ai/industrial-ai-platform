from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.recovery import RecoveryRepository
from app.schemas.recovery import RecoveryReadinessResponse, RecoveryWorkspaceRuntimeResponse
from app.services.readiness_contract import build_readiness_evidence
from app.services.recovery_provider_execution_evidence import provider_execution_evidence_for
from app.services.recovery_resource_identity import (
    APPLICATION_CONFIGURATION,
    OBJECT_STORAGE,
    required_database_authorities,
)
from app.services.recovery_runtime import (
    build_recovery_readiness as build_recovery_readiness_legacy,
)
from app.services.recovery_verification_evidence import (
    REQUIRED_VERIFICATION_CHECKS,
    restore_verification_check_evidence_for,
)


@dataclass(frozen=True)
class ObservedRecoveryObjectives:
    rpo_minutes: float | None
    rto_minutes: float | None


@dataclass(frozen=True)
class AuthoritativeRecoveryChain:
    backup_evidenced: bool
    restore_evidenced: bool
    verification_evidenced: bool

    @property
    def ready(self) -> bool:
        return self.backup_evidenced and self.restore_evidenced and self.verification_evidenced


def _minutes_between(started_at: datetime | None, completed_at: datetime | None) -> float | None:
    if started_at is None or completed_at is None or completed_at < started_at:
        return None
    return round((completed_at - started_at).total_seconds() / 60.0, 3)


def _required_resources(policy) -> tuple[str, ...]:  # noqa: ANN001
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


def _provider_execution_evidenced(
    db: Session,
    *,
    policy,
    execution,
    operation: str,
) -> bool:  # noqa: ANN001
    if execution is None:
        return False
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
            return False
        payload = evidence.evidence_payload
        if payload.get("provider_type") != execution.provider_type:
            return False
        if payload.get("correlation_id") != execution.correlation_id:
            return False
        if not payload.get("provider_execution_id"):
            return False
    return True


def _verification_evidenced(
    db: Session,
    *,
    restore,
    verification,
) -> bool:  # noqa: ANN001
    if restore is None or verification is None:
        return False
    for check_code in REQUIRED_VERIFICATION_CHECKS:
        evidence = restore_verification_check_evidence_for(
            db,
            scope=restore.scope,
            organization_id=restore.organization_id,
            verification_id=verification.id,
            check_code=check_code,
        )
        if evidence is None:
            return False
        if evidence.evidence_payload.get("correlation_id") != restore.correlation_id:
            return False
    return True


def authoritative_recovery_chain(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> AuthoritativeRecoveryChain:
    repo = RecoveryRepository(db)
    policy = repo.active_policy(scope, organization_id)
    if policy is None:
        return AuthoritativeRecoveryChain(False, False, False)

    backup = repo.latest_completed_backup_for_policy(policy.id, scope, organization_id)
    restore = repo.latest_completed_restore_for_policy(policy.id, scope, organization_id)
    verification = repo.latest_passed_verification_for_restore(restore.id) if restore else None
    chain_correlated = bool(
        backup
        and restore
        and verification
        and restore.backup_execution_id == backup.id
        and verification.restore_execution_id == restore.id
    )
    if not chain_correlated:
        return AuthoritativeRecoveryChain(False, False, False)

    return AuthoritativeRecoveryChain(
        backup_evidenced=_provider_execution_evidenced(
            db,
            policy=policy,
            execution=backup,
            operation="backup",
        ),
        restore_evidenced=_provider_execution_evidenced(
            db,
            policy=policy,
            execution=restore,
            operation="restore",
        ),
        verification_evidenced=_verification_evidenced(
            db,
            restore=restore,
            verification=verification,
        ),
    )


def observed_recovery_objectives(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> ObservedRecoveryObjectives:
    repo = RecoveryRepository(db)
    policy = repo.active_policy(scope, organization_id)
    if policy is None:
        return ObservedRecoveryObjectives(rpo_minutes=None, rto_minutes=None)

    backup = repo.latest_completed_backup_for_policy(policy.id, scope, organization_id)
    restore = repo.latest_completed_restore_for_policy(policy.id, scope, organization_id)
    if backup is None or restore is None or restore.backup_execution_id != backup.id:
        return ObservedRecoveryObjectives(rpo_minutes=None, rto_minutes=None)

    verification = repo.latest_passed_verification_for_restore(restore.id)
    rpo_minutes = _minutes_between(backup.completed_at, restore.started_at)
    rto_minutes = _minutes_between(
        restore.started_at,
        verification.completed_at if verification else None,
    )
    return ObservedRecoveryObjectives(rpo_minutes=rpo_minutes, rto_minutes=rto_minutes)


def _replace_gate(
    readiness: RecoveryReadinessResponse,
    *,
    gate_code: str,
    passed: bool,
    summary: str,
    blocker_code: str,
) -> None:
    for gate in readiness.gates:
        if gate.gate_code != gate_code:
            continue
        gate.status = "passed" if passed else "blocked"
        gate.summary = summary
        gate.blocker_code = None if passed else blocker_code
        break


def _gate_passed(readiness: RecoveryReadinessResponse, gate_code: str) -> bool:
    return any(gate.gate_code == gate_code and gate.status == "passed" for gate in readiness.gates)


def build_recovery_readiness(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> RecoveryReadinessResponse:
    readiness = build_recovery_readiness_legacy(
        db,
        scope=scope,
        organization_id=organization_id,
    )
    policy = readiness.active_policy
    objectives = observed_recovery_objectives(
        db,
        scope=scope,
        organization_id=organization_id,
    )
    authoritative_chain = authoritative_recovery_chain(
        db,
        scope=scope,
        organization_id=organization_id,
    )

    legacy_backup_gate_passed = _gate_passed(readiness, "latest_backup_evidence_available")
    _replace_gate(
        readiness,
        gate_code="latest_backup_evidence_available",
        passed=legacy_backup_gate_passed and authoritative_chain.backup_evidenced,
        summary=(
            "Latest completed backup includes required verified artifacts and authoritative provider "
            "execution evidence."
            if legacy_backup_gate_passed and authoritative_chain.backup_evidenced
            else "Latest backup lacks required artifacts or authoritative provider execution evidence."
        ),
        blocker_code="LATEST_BACKUP_EVIDENCE_MISSING",
    )

    legacy_restore_gate_passed = _gate_passed(readiness, "latest_restore_verification_available")
    authoritative_restore_ready = authoritative_chain.restore_evidenced and authoritative_chain.verification_evidenced
    _replace_gate(
        readiness,
        gate_code="latest_restore_verification_available",
        passed=legacy_restore_gate_passed and authoritative_restore_ready,
        summary=(
            "Latest restore has authoritative provider execution and verification check evidence."
            if legacy_restore_gate_passed and authoritative_restore_ready
            else "Latest restore lacks authoritative provider execution or verification check evidence."
        ),
        blocker_code="LATEST_RESTORE_VERIFICATION_MISSING",
    )

    configured_rpo = policy.rpo_minutes if policy else None
    configured_rto = policy.rto_minutes if policy else None
    rpo_met = bool(
        authoritative_chain.ready
        and configured_rpo is not None
        and objectives.rpo_minutes is not None
        and objectives.rpo_minutes <= configured_rpo
    )
    rto_met = bool(
        authoritative_chain.ready
        and configured_rto is not None
        and objectives.rto_minutes is not None
        and objectives.rto_minutes <= configured_rto
    )

    _replace_gate(
        readiness,
        gate_code="rpo_configured",
        passed=rpo_met,
        summary=(
            "Configured RPO target is met by authoritative persisted recovery evidence."
            if rpo_met
            else "Configured RPO target is missing, not authoritatively observable, or exceeded."
        ),
        blocker_code=("RPO_TARGET_NOT_MET" if configured_rpo is not None else "RPO_NOT_CONFIGURED"),
    )
    _replace_gate(
        readiness,
        gate_code="rto_configured",
        passed=rto_met,
        summary=(
            "Configured RTO target is met by authoritative persisted recovery evidence."
            if rto_met
            else "Configured RTO target is missing, not authoritatively observable, or exceeded."
        ),
        blocker_code=("RTO_TARGET_NOT_MET" if configured_rto is not None else "RTO_NOT_CONFIGURED"),
    )

    readiness.rpo = {
        "configured": configured_rpo is not None,
        "minutes": configured_rpo,
        "observed_rpo_minutes": objectives.rpo_minutes if authoritative_chain.ready else None,
        "target_met": rpo_met,
    }
    readiness.rto = {
        "configured": configured_rto is not None,
        "minutes": configured_rto,
        "observed_rto_minutes": objectives.rto_minutes if authoritative_chain.ready else None,
        "target_met": rto_met,
    }

    blockers = [
        {
            "code": gate.blocker_code,
            "gate_code": gate.gate_code,
            "message": gate.summary,
        }
        for gate in readiness.gates
        if gate.status == "blocked"
    ]
    next_actions = list(readiness.next_actions)
    status = "passed" if not blockers else "blocked"
    readiness.evidence_contract = build_readiness_evidence(
        domain="recovery",
        status="stale" if readiness.evidence_contract.status == "stale" else status,
        gate_results=readiness.gates,
        blockers=blockers,
        warnings=readiness.warnings,
        next_actions=next_actions,
        runtime_version=readiness.runtime_version,
        evaluation_timestamp=readiness.evaluation_timestamp,
        expires_at=readiness.expires_at,
        evidence_origin="recovery_readiness_runtime",
        components_evaluated=[
            "policy",
            "backup",
            "backup_provider_execution_evidence",
            "restore",
            "restore_provider_execution_evidence",
            "restore_verification",
            "restore_verification_check_evidence",
            "recovery_objectives",
        ],
        evidence_ids=readiness.evidence_contract.evidence_ids,
        source_runtime_version=readiness.runtime_version,
        supported_runtime_versions=(readiness.runtime_version,),
    )
    readiness.status = readiness.evidence_contract.status
    readiness.reason = readiness.evidence_contract.reason
    readiness.blockers = readiness.evidence_contract.blockers
    readiness.next_actions = readiness.evidence_contract.next_actions
    readiness.evidence_freshness["observed_recovery_objectives"] = {
        "rpo_minutes": objectives.rpo_minutes if authoritative_chain.ready else None,
        "rto_minutes": objectives.rto_minutes if authoritative_chain.ready else None,
    }
    readiness.evidence_freshness["physical_provider_execution"] = {
        "backup_evidenced": authoritative_chain.backup_evidenced,
        "restore_evidenced": authoritative_chain.restore_evidenced,
        "verification_evidenced": authoritative_chain.verification_evidenced,
        "required_by_recovery_control_plane": True,
        "ready": authoritative_chain.ready,
    }
    return readiness


def build_recovery_workspace_runtime(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> RecoveryWorkspaceRuntimeResponse:
    readiness = build_recovery_readiness(
        db,
        scope=scope,
        organization_id=organization_id,
    )
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
