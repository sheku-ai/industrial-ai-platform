from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.observability import HealthEvaluation
from app.models.production_acceptance import ProductionAcceptanceRun
from app.models.recovery import RecoveryEvidence
from app.models.release_operational_evidence import ReleaseOperationalEvidence
from app.repositories.observability import ObservabilityRepository
from app.repositories.recovery import RecoveryRepository
from app.repositories.release_governance import ReleaseGovernanceRepository
from app.repositories.release_operational_evidence import ReleaseOperationalEvidenceRepository
from app.schemas.production_acceptance import (
    ConfigurationPreflightCheck,
    ConfigurationPreflightResult,
    ProductionBlocker,
)
from app.schemas.release_operational_evidence import (
    BackupEvidenceContract,
    OperationalEvidenceRead,
    OperationalEvidenceRequest,
)
from app.services.configuration_preflight import build_configuration_preflight
from app.services.database_revision import resolve_database_revision

SUPPORTED_RELEASE_EDITIONS = frozenset({"community", "enterprise"})
RC_REFRESH_REQUIRED_SOURCE_TYPES = frozenset(
    {
        "configuration_preflight",
        "backup_execution_completed",
        "observability_health_evaluation",
        "production_acceptance_run",
        "upgrade_readiness",
        "rollback_eligibility",
    }
)
RC_REFRESH_PASSED_STATUSES = frozenset({"passed", "requires_restore"})
OPERATIONAL_EXECUTION_KEY_PREFIXES = {
    "configuration_preflight": "configuration-preflight",
    "upgrade_readiness": "upgrade",
    "rollback_eligibility": "rollback",
    "rc_operational_refresh": "rc-refresh",
}


@dataclass(frozen=True)
class _ResolvedRcSource:
    id: str
    evidence_type: str
    status: str
    scope: str
    organization_id: uuid.UUID | None
    evaluated_at: datetime
    expires_at: datetime | None
    evidence_hash: str
    backup_execution_id: uuid.UUID | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _effective_edition(requested_edition: str | None) -> str:
    configured_edition = get_settings().platform_edition.strip().lower()
    if configured_edition not in SUPPORTED_RELEASE_EDITIONS:
        raise ValueError("unsupported_platform_edition")
    if requested_edition is not None and requested_edition != configured_edition:
        raise ValueError("release_edition_mismatch")
    return configured_edition


def resolve_release_manifest_edition(
    manifest: dict[str, Any],
    requested_edition: str | None,
) -> str:
    edition = _effective_edition(requested_edition)
    supported_editions = manifest.get("supported_editions")
    if not isinstance(supported_editions, list) or set(supported_editions) != SUPPORTED_RELEASE_EDITIONS:
        raise ValueError("release_manifest_supported_editions_invalid")
    if "edition" in manifest:
        raise ValueError("release_manifest_base_edition_forbidden")
    identity = manifest.get("edition_manifest")
    if not isinstance(identity, dict):
        raise ValueError("release_edition_manifest_required")
    if identity.get("edition") != edition:
        raise ValueError("release_edition_manifest_mismatch")
    if identity.get("version") != manifest.get("version"):
        raise ValueError("release_edition_manifest_version_mismatch")
    if identity.get("alembic_head") != manifest.get("alembic_head"):
        raise ValueError("release_edition_manifest_alembic_mismatch")
    if identity.get("ai_required") is not False:
        raise ValueError("release_edition_ai_must_remain_optional")
    if edition == "community" and identity.get("enterprise_dependency_required") is not False:
        raise ValueError("community_edition_enterprise_dependency_forbidden")
    return edition


def build_operational_execution_key(
    evidence_type: str,
    edition: str,
    release_version: str,
    execution_identity: str,
) -> str:
    prefix = OPERATIONAL_EXECUTION_KEY_PREFIXES.get(evidence_type)
    if prefix is None:
        raise ValueError("unsupported_operational_evidence_type")
    if edition not in SUPPORTED_RELEASE_EDITIONS:
        raise ValueError("unsupported_platform_edition")
    if not execution_identity.strip():
        raise ValueError("operational_execution_identity_required")
    return f"{prefix}:{edition}:{release_version}:{execution_identity}"


def _validate_operational_execution_key(
    evidence_type: str,
    edition: str,
    release_version: str,
    execution_key: str,
) -> None:
    prefix = OPERATIONAL_EXECUTION_KEY_PREFIXES.get(evidence_type)
    if prefix is None:
        raise ValueError("unsupported_operational_evidence_type")
    expected_prefix = f"{prefix}:{edition}:{release_version}"
    if not execution_key.startswith(f"{expected_prefix}:"):
        raise ValueError("operational_execution_key_edition_required")


def _safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe(item) for item in value]
    return value


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_safe(value), sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _deterministic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _deterministic(item)
            for key, item in value.items()
            if key not in {"evaluated_at", "duration_ms", "evaluation_duration"}
        }
    if isinstance(value, list | tuple):
        return [_deterministic(item) for item in value]
    return _safe(value)


def get_backup_evidence_contract(
    db: Session,
    backup_id: uuid.UUID,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> BackupEvidenceContract:
    repository = RecoveryRepository(db)
    evidence = repository.get_evidence(backup_id)
    if evidence is not None:
        if (
            evidence.scope != scope
            or evidence.organization_id != organization_id
            or evidence.evidence_type != "backup_execution_completed"
            or evidence.source_entity_type != "backup_execution"
        ):
            raise ValueError("backup_evidence_scope_mismatch")
        try:
            resolved_backup_id = uuid.UUID(evidence.source_entity_id)
        except ValueError as exc:
            raise ValueError("backup_evidence_source_invalid") from exc
    else:
        resolved_backup_id = backup_id
    backup = repository.get_backup(resolved_backup_id, scope, organization_id)
    if backup is None:
        raise ValueError("backup_evidence_not_found")
    evidence = evidence or repository.backup_completion_evidence(backup.id)
    if evidence is None or evidence.status != "passed" or backup.status != "completed":
        raise ValueError("backup_evidence_not_passed")
    if evidence.expires_at is None or evidence.expires_at <= _now():
        raise ValueError("backup_evidence_expired")
    expected_hash = stable_hash(
        {
            "scope": evidence.scope,
            "organization_id": evidence.organization_id,
            "evidence_type": evidence.evidence_type,
            "source_entity_type": evidence.source_entity_type,
            "source_entity_id": evidence.source_entity_id,
            "status": evidence.status,
            "payload": evidence.evidence_payload,
        }
    )
    if expected_hash != evidence.evidence_hash:
        raise ValueError("backup_evidence_integrity_invalid")
    payload = dict(evidence.evidence_payload)
    payload.update(
        {
            "evidence_id": evidence.id,
            "backup_id": backup.id,
            "scope": backup.scope,
            "organization_id": backup.organization_id,
            "provider": backup.provider_type,
            "started_at": backup.started_at,
            "completed_at": backup.completed_at,
            "expires_at": evidence.expires_at,
            "correlation_id": backup.correlation_id,
            "execution_key": backup.idempotency_key,
            "error_code": backup.failure_code,
            "error_detail": backup.failure_summary,
        }
    )
    try:
        contract = BackupEvidenceContract.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("backup_evidence_contract_incomplete") from exc
    if not contract.provider_reference.strip():
        raise ValueError("backup_provider_reference_missing")
    if not contract.integrity_verified:
        raise ValueError("backup_evidence_integrity_not_verified")
    return contract


def _persist(
    db: Session,
    *,
    request: OperationalEvidenceRequest,
    evidence_type: str,
    status: str,
    payload: dict[str, Any],
    source_evidence_ids: list[str],
    expires_at: datetime | None,
    backup_execution_id: uuid.UUID | None = None,
) -> OperationalEvidenceRead:
    repository = ReleaseOperationalEvidenceRepository(db)
    effective_edition = _effective_edition(request.edition)
    _validate_operational_execution_key(
        evidence_type,
        effective_edition,
        request.release_version,
        request.execution_key,
    )
    input_payload = {
        "scope": request.scope,
        "organization_id": request.organization_id,
        "release_version": request.release_version,
        "alembic_revision": request.alembic_revision,
        "edition": effective_edition,
        "backup_evidence_id": request.backup_evidence_id,
        "payload": _deterministic(payload),
    }
    input_hash = stable_hash(input_payload)
    existing = repository.find_execution(
        scope=request.scope,
        organization_id=request.organization_id,
        evidence_type=evidence_type,
        execution_key=request.execution_key,
    )
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("idempotency_key_conflict")
        return OperationalEvidenceRead.model_validate(existing)
    evaluated_at = _now()
    safe_payload = _safe(payload)
    row = ReleaseOperationalEvidence(
        organization_id=request.organization_id,
        backup_execution_id=backup_execution_id,
        scope=request.scope,
        evidence_type=evidence_type,
        release_version=request.release_version,
        alembic_revision=request.alembic_revision,
        edition=effective_edition,
        status=status,
        execution_key=request.execution_key,
        correlation_id=request.correlation_id or f"{evidence_type}:{uuid.uuid4()}",
        input_hash=input_hash,
        evidence_payload=safe_payload,
        evidence_hash=stable_hash(safe_payload),
        source_evidence_ids=source_evidence_ids,
        evaluated_at=evaluated_at,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return OperationalEvidenceRead.model_validate(row)


def refresh_configuration_preflight(
    db: Session,
    request: OperationalEvidenceRequest,
) -> OperationalEvidenceRead:
    settings = get_settings()
    edition = _effective_edition(request.edition)
    request = request.model_copy(update={"edition": edition})
    result = build_configuration_preflight("production", db=db, probe_dependencies=True)
    database_revision = resolve_database_revision(db)
    coherence = (
        ("release_manifest_version_matches", settings.app_version == request.release_version),
        ("release_manifest_alembic_head_matches", database_revision == request.alembic_revision),
        (
            "release_manifest_edition_matches",
            edition == settings.platform_edition.strip().lower()
            and settings.feature_enterprise_extensions_enabled
            == (edition == "enterprise"),
        ),
    )
    checks = list(result.checks)
    blockers = list(result.blockers)
    evaluated_at = _now()
    for code, passed in coherence:
        checks.append(
            ConfigurationPreflightCheck(
                setting_code=code,
                status="passed" if passed else "failed",
                source="release.manifest",
                masked_value="configured",
                reason="configured" if passed else "release_manifest_mismatch",
                mandatory=True,
                configured=True,
                placeholder=False,
                evidence_origin="release_operational_evidence_runtime",
                evaluated_at=evaluated_at,
            )
        )
        if not passed:
            blockers.append(
                ProductionBlocker(
                    code=f"{code}_not_ready",
                    gate_code=code,
                    domain="configuration",
                    message="release_manifest_mismatch",
                )
            )
    if blockers:
        result = result.model_copy(update={"status": "failed", "checks": checks, "blockers": blockers})
    else:
        result = result.model_copy(update={"checks": checks})
    return _persist(
        db,
        request=request,
        evidence_type="configuration_preflight",
        status=result.status,
        payload=result.model_dump(mode="json"),
        source_evidence_ids=[],
        expires_at=evaluated_at
        + timedelta(seconds=settings.configuration_preflight_evidence_max_age_seconds),
    )


def configuration_preflight_from_evidence(row: ReleaseOperationalEvidence) -> ConfigurationPreflightResult:
    if row.evidence_hash != stable_hash(row.evidence_payload):
        raise ValueError("configuration_preflight_evidence_corrupt")
    if row.expires_at is None or row.expires_at <= _now():
        raise ValueError("configuration_preflight_evidence_expired")
    try:
        return ConfigurationPreflightResult.model_validate(row.evidence_payload)
    except ValidationError as exc:
        raise ValueError("configuration_preflight_evidence_incompatible") from exc


def evaluate_upgrade_readiness(
    db: Session,
    request: OperationalEvidenceRequest,
    manifest: dict[str, Any],
) -> OperationalEvidenceRead:
    edition = resolve_release_manifest_edition(manifest, request.edition)
    request = request.model_copy(update={"edition": edition})
    if request.backup_evidence_id is None:
        raise ValueError("backup_evidence_id_required")
    backup = get_backup_evidence_contract(
        db,
        request.backup_evidence_id,
        scope=request.scope,
        organization_id=request.organization_id,
    )
    allowed_sources = manifest.get("upgrade_from", [])
    repository_heads = manifest.get("repository_heads", [])
    supported_postgresql = str(manifest.get("supported_postgresql_version") or "")
    postgresql_compatible = backup.postgresql_version.split(".", 1)[0] == supported_postgresql.split(".", 1)[0]
    release_repository = ReleaseGovernanceRepository(db)
    governed_release = next(
        (
            release
            for release in release_repository.list_releases()
            if release.version == request.release_version
            and release.edition == edition
        ),
        None,
    )
    migration_path = (
        next(
            (
                item
                for item in release_repository.list_migration_requirements(governed_release.id)
                if item.from_revision == backup.alembic_revision
                and item.to_revision == request.alembic_revision
            ),
            None,
        )
        if governed_release
        else None
    )
    checks = {
        "backup_passed": backup.status == "passed",
        "backup_integrity_verified": backup.integrity_verified,
        "backup_revision_matches_source": backup.alembic_revision != request.alembic_revision,
        "backup_version_allowed": backup.application_version in allowed_sources,
        "target_version_matches_manifest": manifest.get("version") == request.release_version,
        "target_revision_matches_manifest": manifest.get("alembic_head") == request.alembic_revision,
        "repository_has_single_target_head": repository_heads == [request.alembic_revision],
        "postgresql_version_compatible": postgresql_compatible,
        "governed_release_found": governed_release is not None,
        "governed_migration_path_found": migration_path is not None,
        "automatic_downgrade_disabled": True,
    }
    blockers = [code for code, passed in checks.items() if not passed]
    payload = {
        "checks": checks,
        "blockers": blockers,
        "source_application_version": backup.application_version,
        "source_alembic_revision": backup.alembic_revision,
        "target_application_version": request.release_version,
        "target_alembic_revision": request.alembic_revision,
        "migration_applied": False,
    }
    return _persist(
        db,
        request=request,
        evidence_type="upgrade_readiness",
        status="passed" if not blockers else "blocked",
        payload=payload,
        source_evidence_ids=[str(backup.evidence_id)],
        expires_at=backup.expires_at,
        backup_execution_id=backup.backup_id,
    )


def evaluate_rollback_eligibility(
    db: Session,
    request: OperationalEvidenceRequest,
    manifest: dict[str, Any],
) -> OperationalEvidenceRead:
    edition = resolve_release_manifest_edition(manifest, request.edition)
    request = request.model_copy(update={"edition": edition})
    if request.backup_evidence_id is None:
        raise ValueError("backup_evidence_id_required")
    backup = get_backup_evidence_contract(
        db,
        request.backup_evidence_id,
        scope=request.scope,
        organization_id=request.organization_id,
    )
    target = manifest.get("rollback_target")
    release_repository = ReleaseGovernanceRepository(db)
    current_release = next(
        (
            release
            for release in release_repository.list_releases(edition=edition)
            if release.version == request.release_version
        ),
        None,
    )
    target_release = next(
        (
            release
            for release in release_repository.list_releases(edition=edition)
            if release.version == target
        ),
        None,
    )
    rollback_contract = (
        release_repository.get_rollback_target(current_release.id) if current_release else None
    )
    self_rollback = bool(
        target == request.release_version
        or current_release
        and rollback_contract
        and rollback_contract.rollback_target_release_id == current_release.id
    )
    application_compatible = bool(
        target_release
        and target == backup.application_version
        and rollback_contract
        and rollback_contract.rollback_target_release_id == target_release.id
        and rollback_contract.application_rollback_supported
    )
    migrations = (
        release_repository.list_migration_requirements(current_release.id) if current_release else []
    )
    irreversible_migration = any(not item.reversible for item in migrations)
    restore_required = bool(
        irreversible_migration
        or manifest.get("database_rollback_policy")
        == "restore_required_when_migration_is_not_reversible"
    )
    blockers = []
    if self_rollback:
        blockers.append("self_rollback_forbidden")
    if not application_compatible:
        blockers.append("rollback_target_backup_version_mismatch")
    if not backup.integrity_verified:
        blockers.append("backup_integrity_not_verified")
    if current_release is None or target_release is None or rollback_contract is None:
        blockers.append("governed_rollback_contract_missing")
    if blockers:
        status = "blocked"
    elif restore_required:
        status = "requires_restore"
    else:
        status = "passed"
    payload = {
        "application_rollback_eligible": not blockers,
        "data_rollback_eligible": not blockers and not restore_required,
        "application_rollback_supported": bool(
            rollback_contract and rollback_contract.application_rollback_supported
        ),
        "database_rollback_supported": bool(
            rollback_contract and rollback_contract.database_rollback_supported
        ),
        "restore_required": restore_required,
        "rollback_target": target,
        "self_rollback_forbidden": self_rollback,
        "blockers": blockers,
        "database_downgrade_executed": False,
        "restore_executed": False,
        "rollback_executed": False,
    }
    return _persist(
        db,
        request=request,
        evidence_type="rollback_eligibility",
        status=status,
        payload=payload,
        source_evidence_ids=[str(backup.evidence_id)],
        expires_at=backup.expires_at,
        backup_execution_id=backup.backup_id,
    )


def _validate_source_scope(
    *,
    source_scope: str,
    source_organization_id: uuid.UUID | None,
    request: OperationalEvidenceRequest,
) -> None:
    if source_scope != request.scope:
        raise ValueError("rc_refresh_source_scope_mismatch")
    if source_organization_id != request.organization_id:
        raise ValueError("rc_refresh_source_organization_mismatch")


def _resolve_rc_source(
    db: Session,
    source_id: uuid.UUID,
    request: OperationalEvidenceRequest,
) -> _ResolvedRcSource:
    release_evidence = db.get(ReleaseOperationalEvidence, source_id)
    if release_evidence is not None:
        _validate_source_scope(
            source_scope=release_evidence.scope,
            source_organization_id=release_evidence.organization_id,
            request=request,
        )
        if release_evidence.evidence_hash != stable_hash(release_evidence.evidence_payload):
            raise ValueError("rc_refresh_source_hash_invalid")
        return _ResolvedRcSource(
            id=str(release_evidence.id),
            evidence_type=release_evidence.evidence_type,
            status=release_evidence.status,
            scope=release_evidence.scope,
            organization_id=release_evidence.organization_id,
            evaluated_at=release_evidence.evaluated_at,
            expires_at=release_evidence.expires_at,
            evidence_hash=release_evidence.evidence_hash,
            backup_execution_id=release_evidence.backup_execution_id,
        )

    recovery_evidence = db.get(RecoveryEvidence, source_id)
    if recovery_evidence is not None:
        _validate_source_scope(
            source_scope=recovery_evidence.scope,
            source_organization_id=recovery_evidence.organization_id,
            request=request,
        )
        if recovery_evidence.evidence_type != "backup_execution_completed":
            raise ValueError("rc_refresh_source_type_not_allowed")
        backup = get_backup_evidence_contract(
            db,
            recovery_evidence.id,
            scope=request.scope,
            organization_id=request.organization_id,
        )
        return _ResolvedRcSource(
            id=str(recovery_evidence.id),
            evidence_type="backup_execution_completed",
            status=recovery_evidence.status,
            scope=recovery_evidence.scope,
            organization_id=recovery_evidence.organization_id,
            evaluated_at=recovery_evidence.observed_at,
            expires_at=recovery_evidence.expires_at,
            evidence_hash=recovery_evidence.evidence_hash,
            backup_execution_id=backup.backup_id,
        )

    evaluation = db.get(HealthEvaluation, source_id)
    if evaluation is not None:
        _validate_source_scope(
            source_scope=evaluation.scope,
            source_organization_id=evaluation.organization_id,
            request=request,
        )
        observability = ObservabilityRepository(db)
        acceptance = observability.acceptance(evaluation.id)
        evidence = observability.evidence(evaluation.id)
        if acceptance is None or acceptance.status != "passed" or evaluation.acceptance_status != "passed":
            status = "failed"
        elif not evidence:
            status = "not_evaluated"
        elif any(item.expires_at <= _now() for item in evidence):
            status = "expired"
        else:
            status = "passed"
        return _ResolvedRcSource(
            id=str(evaluation.id),
            evidence_type="observability_health_evaluation",
            status=status,
            scope=evaluation.scope,
            organization_id=evaluation.organization_id,
            evaluated_at=evaluation.evaluated_at,
            expires_at=min((item.expires_at for item in evidence), default=None),
            evidence_hash=stable_hash(
                {
                    "evaluation": evaluation.result_hash,
                    "acceptance": acceptance.result_hash if acceptance is not None else None,
                    "evidence": [item.evidence_hash for item in evidence],
                }
            ),
        )

    acceptance_run = db.get(ProductionAcceptanceRun, source_id)
    if acceptance_run is not None:
        _validate_source_scope(
            source_scope=acceptance_run.scope,
            source_organization_id=acceptance_run.organization_id,
            request=request,
        )
        from app.services.production_acceptance_runtime import get_production_acceptance_run

        result = get_production_acceptance_run(
            db,
            acceptance_run.id,
            scope=request.scope,
            organization_id=request.organization_id,
        )
        if result is None:
            raise ValueError("rc_refresh_production_acceptance_not_found")
        return _ResolvedRcSource(
            id=str(acceptance_run.id),
            evidence_type="production_acceptance_run",
            status="passed" if result.status == "passed" and result.production_ready else result.status,
            scope=acceptance_run.scope,
            organization_id=acceptance_run.organization_id,
            evaluated_at=result.evaluation_timestamp,
            expires_at=result.expires_at,
            evidence_hash=result.result_hash or "",
        )

    raise ValueError("rc_refresh_source_not_found")


def _source_payload(source: _ResolvedRcSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "evidence_type": source.evidence_type,
        "status": source.status,
        "scope": source.scope,
        "organization_id": str(source.organization_id) if source.organization_id else None,
        "evaluated_at": source.evaluated_at,
        "expires_at": source.expires_at,
        "evidence_hash": source.evidence_hash,
    }


def persist_operational_refresh_summary(
    db: Session,
    request: OperationalEvidenceRequest,
    summary: dict[str, Any],
    source_evidence_ids: list[str],
) -> OperationalEvidenceRead:
    edition = _effective_edition(request.edition)
    request = request.model_copy(update={"edition": edition})
    source_ids = sorted(set(source_evidence_ids))
    blockers: list[dict[str, str]] = []
    resolved_sources: list[_ResolvedRcSource] = []
    if not source_ids:
        blockers.append({"code": "rc_refresh_source_evidence_required"})
    if len(source_ids) != len(source_evidence_ids):
        blockers.append({"code": "rc_refresh_duplicate_source_evidence"})

    for raw_source_id in source_ids:
        try:
            source_id = uuid.UUID(raw_source_id)
        except ValueError:
            blockers.append({"code": "rc_refresh_source_id_invalid", "source_id": raw_source_id})
            continue
        try:
            source = _resolve_rc_source(db, source_id, request)
        except ValueError as exc:
            blockers.append({"code": str(exc), "source_id": raw_source_id})
            continue
        resolved_sources.append(source)
        try:
            _validate_source_scope(
                source_scope=source.scope,
                source_organization_id=source.organization_id,
                request=request,
            )
        except ValueError as exc:
            blockers.append({"code": str(exc), "source_id": source.id})
        if source.evidence_type not in RC_REFRESH_REQUIRED_SOURCE_TYPES:
            blockers.append({"code": "rc_refresh_source_type_not_allowed", "source_id": source.id})
        allowed_statuses = (
            RC_REFRESH_PASSED_STATUSES
            if source.evidence_type == "rollback_eligibility"
            else frozenset({"passed"})
        )
        if source.status not in allowed_statuses:
            blockers.append(
                {
                    "code": "rc_refresh_source_status_not_accepted",
                    "source_id": source.id,
                    "status": source.status,
                }
            )
        if source.expires_at is None:
            blockers.append({"code": "rc_refresh_source_expiry_required", "source_id": source.id})
        elif source.expires_at <= _now():
            blockers.append({"code": "rc_refresh_source_expired", "source_id": source.id})

    resolved_types = [source.evidence_type for source in resolved_sources]
    missing_types = sorted(RC_REFRESH_REQUIRED_SOURCE_TYPES - set(resolved_types))
    if missing_types:
        blockers.append({"code": "rc_refresh_required_source_missing", "types": ",".join(missing_types)})
    duplicate_types = sorted(
        source_type for source_type in set(resolved_types) if resolved_types.count(source_type) > 1
    )
    if duplicate_types:
        blockers.append({"code": "rc_refresh_duplicate_source_type", "types": ",".join(duplicate_types)})
    if request.backup_evidence_id is not None:
        backup_source = next(
            (source for source in resolved_sources if source.id == str(request.backup_evidence_id)),
            None,
        )
        if backup_source is None:
            blockers.append({"code": "rc_refresh_backup_evidence_not_in_lineage"})
        elif backup_source.evidence_type != "backup_execution_completed":
            blockers.append({"code": "rc_refresh_backup_evidence_type_invalid"})

    valid_expirations = [source.expires_at for source in resolved_sources if source.expires_at is not None]
    expires_at = min(valid_expirations) if valid_expirations else None
    status = "blocked" if blockers else "passed"
    payload = {
        "client_summary_ignored": True,
        "resolved_sources": [_source_payload(source) for source in resolved_sources],
        "required_source_types": sorted(RC_REFRESH_REQUIRED_SOURCE_TYPES),
        "blockers": blockers,
        "deployment_performed": False,
        "rollback_performed": False,
        "llm_used": False,
        "embeddings_used": False,
        "vector_database_used": False,
    }
    backup_execution_id = next(
        (
            source.backup_execution_id
            for source in resolved_sources
            if source.evidence_type == "backup_execution_completed"
        ),
        None,
    )
    return _persist(
        db,
        request=request,
        evidence_type="rc_operational_refresh",
        status=status,
        payload=payload,
        source_evidence_ids=source_ids,
        expires_at=expires_at if status == "passed" else expires_at,
        backup_execution_id=backup_execution_id,
    )
