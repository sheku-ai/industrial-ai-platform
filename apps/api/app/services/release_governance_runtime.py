from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.release_governance import (
    GovernedRelease,
    ReleaseAcceptanceEvidence,
    ReleaseArtifact,
    ReleaseBuild,
    ReleaseBuildManifest,
    ReleaseCompatibility,
    ReleaseDeploymentManifest,
    ReleaseMigrationRequirement,
    ReleaseRollbackTarget,
)
from app.repositories.release_governance import ReleaseGovernanceRepository
from app.schemas.release_governance import (
    BuildManifestCreate,
    DeploymentManifestCreate,
    GovernedReleaseCreate,
    GovernedReleaseUpdate,
    LatestReleaseReadinessResponse,
    LatestReleaseResponse,
    MigrationRequirementCreate,
    ReleaseAcceptanceRead,
    ReleaseArtifactCreate,
    ReleaseArtifactVerify,
    ReleaseBuildComplete,
    ReleaseBuildCreate,
    ReleaseCompatibilityCreate,
    ReleaseReadinessResponse,
    RollbackTargetCreate,
    mask_artifact_location,
)
from app.services.readiness_contract import build_readiness_evidence

CONTRACT_VERSION = "release_artifact_governance.v1"
DETERMINISTIC_IDENTITY_CHANNELS = frozenset({"stable", "release_candidate"})


def _now() -> datetime:
    return datetime.now(UTC)


def _safe(value: Any) -> Any:
    if isinstance(value, datetime | uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe(item) for item in value]
    return value


def stable_hash(value: Any) -> str:
    encoded = json.dumps(_safe(value), sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def governed_release_logical_identity(payload: GovernedReleaseCreate) -> dict[str, str]:
    return {
        "edition": payload.edition.strip().lower(),
        "version": payload.version.strip(),
        "channel": payload.channel.strip().lower(),
        "contract_version": CONTRACT_VERSION,
        "source_repository": payload.source_repository.strip(),
        "source_revision": payload.source_revision.strip(),
    }


def governed_release_identity_hash(payload: GovernedReleaseCreate) -> str:
    return stable_hash(governed_release_logical_identity(payload))


def governed_release_code(payload: GovernedReleaseCreate) -> str:
    identity_hash = governed_release_identity_hash(payload)
    version = re.sub(r"[^A-Za-z0-9._-]+", "-", payload.version).strip("-") or "release"
    prefix = f"governed-{payload.edition}-{payload.channel}-{version}"
    return f"{prefix[:115]}-{identity_hash[:12]}"


def governed_release_idempotency_key(payload: GovernedReleaseCreate) -> str:
    return f"governed-release:{governed_release_identity_hash(payload)}"


def _deterministic_release_payload(payload: GovernedReleaseCreate) -> GovernedReleaseCreate:
    if payload.channel not in DETERMINISTIC_IDENTITY_CHANNELS:
        return payload
    normalized = payload.model_copy(
        update={
            "edition": payload.edition.strip().lower(),
            "version": payload.version.strip(),
            "channel": payload.channel.strip().lower(),
            "source_repository": payload.source_repository.strip(),
            "source_revision": payload.source_revision.strip(),
            "source_branch": payload.source_branch.strip() if payload.source_branch else None,
        }
    )
    return normalized.model_copy(
        update={
            "release_code": governed_release_code(normalized),
            "idempotency_key": governed_release_idempotency_key(normalized),
        }
    )


def _logical_identity_matches(release: GovernedRelease, payload: GovernedReleaseCreate) -> bool:
    identity = governed_release_logical_identity(payload)
    return all(getattr(release, field) == value for field, value in identity.items())


def _require_release(repository: ReleaseGovernanceRepository, release_id: uuid.UUID) -> GovernedRelease:
    release = repository.get_release(release_id)
    if release is None:
        raise LookupError("release_not_found")
    return release


def _require_build(repository: ReleaseGovernanceRepository, build_id: uuid.UUID) -> ReleaseBuild:
    build = repository.get_build(build_id)
    if build is None:
        raise LookupError("build_not_found")
    return build


def create_release(db: Session, payload: GovernedReleaseCreate) -> GovernedRelease:
    repository = ReleaseGovernanceRepository(db)
    payload = _deterministic_release_payload(payload)
    deterministic = payload.channel in DETERMINISTIC_IDENTITY_CHANNELS
    input_hash = (
        governed_release_identity_hash(payload)
        if deterministic
        else stable_hash(payload.model_dump(mode="json", exclude={"created_by"}))
    )
    existing = repository.get_release_by_idempotency(payload.idempotency_key)
    if existing is not None:
        if (
            (deterministic and not _logical_identity_matches(existing, payload))
            or (not deterministic and existing.input_hash != input_hash)
            or existing.source_branch != payload.source_branch
        ):
            raise ValueError("idempotency_key_conflict")
        return existing
    if deterministic:
        logical_matches = repository.list_releases_by_logical_identity(
            **governed_release_logical_identity(payload)
        )
        if logical_matches:
            canonical = logical_matches[0]
            if canonical.source_branch != payload.source_branch:
                raise ValueError("governed_release_payload_conflict")
            return canonical
    if repository.get_release_by_code(payload.release_code) is not None:
        raise ValueError("release_code_conflict")
    release = GovernedRelease(
        **payload.model_dump(),
        status="draft",
        contract_version=CONTRACT_VERSION,
        input_hash=input_hash,
    )
    db.add(release)
    db.flush()
    return release


def update_release(db: Session, release_id: uuid.UUID, payload: GovernedReleaseUpdate) -> GovernedRelease:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    changes = payload.model_dump(exclude_unset=True)
    requested_status = changes.pop("status", None)
    if requested_status in {"validated", "approved"}:
        acceptance = repository.latest_acceptance(release.id)
        if acceptance is None or acceptance.status != "passed":
            raise ValueError("release_acceptance_required")
    for key, value in changes.items():
        setattr(release, key, value)
    if requested_status:
        release.status = requested_status
        now = _now()
        if requested_status == "approved":
            release.approved_at = now
        elif requested_status == "retired":
            release.retired_at = now
    release.result_hash = stable_hash(
        {"release_id": release.id, "version": release.version, "channel": release.channel, "status": release.status}
    )
    db.add(release)
    db.flush()
    return release


def create_build(db: Session, release_id: uuid.UUID, payload: ReleaseBuildCreate) -> ReleaseBuild:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    if payload.source_revision != release.source_revision:
        raise ValueError("build_source_revision_mismatch")
    input_hash = stable_hash(payload.model_dump(mode="json"))
    existing = repository.get_build_by_idempotency(release_id, payload.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("idempotency_key_conflict")
        return existing
    build = ReleaseBuild(
        release_id=release_id,
        **payload.model_dump(),
        build_status="planned",
        reproducible=False,
        input_hash=input_hash,
    )
    db.add(build)
    release.status = "assembling"
    db.add(release)
    db.flush()
    return build


def register_build_manifest(db: Session, build_id: uuid.UUID, payload: BuildManifestCreate) -> ReleaseBuildManifest:
    repository = ReleaseGovernanceRepository(db)
    build = _require_build(repository, build_id)
    release = _require_release(repository, build.release_id)
    if payload.application_version != release.version or payload.source_revision != release.source_revision:
        raise ValueError("build_manifest_release_mismatch")
    if payload.build_timestamp != build.build_timestamp:
        raise ValueError("build_manifest_timestamp_mismatch")
    manifest_payload = payload.model_dump(mode="json")
    manifest_hash = stable_hash(manifest_payload)
    existing = repository.get_build_manifest(build_id)
    if existing is not None:
        if existing.manifest_hash != manifest_hash:
            raise ValueError("build_manifest_conflict")
        return existing
    manifest = ReleaseBuildManifest(build_id=build_id, **payload.model_dump(), manifest_hash=manifest_hash)
    db.add(manifest)
    db.flush()
    return manifest


def complete_build(db: Session, build_id: uuid.UUID, payload: ReleaseBuildComplete) -> ReleaseBuild:
    repository = ReleaseGovernanceRepository(db)
    build = _require_build(repository, build_id)
    manifest = repository.get_build_manifest(build_id)
    if manifest is None:
        raise ValueError("build_manifest_required")
    evidence = payload.reproducibility_evidence
    reproducible = bool(
        evidence.get("repeated_build_digest_match") is True and int(evidence.get("independent_attempts") or 0) >= 2
    )
    result = {
        "build_id": build.id,
        "manifest_hash": manifest.manifest_hash,
        "reproducibility_evidence": evidence,
        "result_evidence": payload.result_evidence,
    }
    result_hash = stable_hash(result)
    if build.build_status == "completed":
        if build.result_hash != result_hash:
            raise ValueError("build_completion_conflict")
        return build
    build.build_status = "completed"
    build.completed_at = _now()
    build.reproducibility_evidence = evidence
    build.reproducible = reproducible
    build.result_hash = result_hash
    db.add(build)
    db.flush()
    return build


def register_deployment_manifest(
    db: Session, release_id: uuid.UUID, payload: DeploymentManifestCreate
) -> ReleaseDeploymentManifest:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    build = _require_build(repository, payload.build_id)
    if build.release_id != release_id:
        raise ValueError("deployment_manifest_build_mismatch")
    if payload.rollback_target_release_id == release_id:
        raise ValueError("rollback_target_cannot_reference_same_release")
    if payload.rollback_target_release_id is not None:
        target = _require_release(repository, payload.rollback_target_release_id)
        if target.edition != release.edition:
            raise ValueError("rollback_target_edition_mismatch")
    manifest_hash = stable_hash(payload.model_dump(mode="json"))
    existing = repository.get_deployment_manifest(release_id)
    if existing is not None:
        if existing.manifest_hash != manifest_hash:
            raise ValueError("deployment_manifest_conflict")
        return existing
    manifest = ReleaseDeploymentManifest(release_id=release_id, **payload.model_dump(), manifest_hash=manifest_hash)
    db.add(manifest)
    if repository.get_build_manifest(build.id) is not None:
        release.status = "ready_for_validation"
        release.prepared_at = _now()
        db.add(release)
    db.flush()
    return manifest


def register_artifact(db: Session, release_id: uuid.UUID, payload: ReleaseArtifactCreate) -> ReleaseArtifact:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    build = _require_build(repository, payload.build_id)
    if build.release_id != release_id:
        raise ValueError("artifact_build_mismatch")
    if payload.edition != release.edition:
        raise ValueError("artifact_edition_mismatch")
    existing = repository.get_artifact_by_code(release_id, build.id, payload.artifact_code)
    input_hash = stable_hash(payload.model_dump(mode="json"))
    if existing is not None:
        if existing.metadata_payload.get("registration_input_hash") != input_hash:
            raise ValueError("artifact_code_conflict")
        return existing
    metadata = dict(payload.metadata_payload)
    metadata["registration_input_hash"] = input_hash
    values = payload.model_dump(exclude={"artifact_location", "metadata_payload"})
    artifact = ReleaseArtifact(
        release_id=release_id,
        **values,
        artifact_location_masked=mask_artifact_location(payload.artifact_location),
        metadata_payload=metadata,
        status="registered",
    )
    db.add(artifact)
    db.flush()
    return artifact


def verify_artifact(db: Session, artifact_id: uuid.UUID, payload: ReleaseArtifactVerify) -> ReleaseArtifact:
    repository = ReleaseGovernanceRepository(db)
    artifact = repository.get_artifact(artifact_id)
    if artifact is None:
        raise LookupError("artifact_not_found")
    checksum_valid = payload.checksum_verified and bool(artifact.checksum and artifact.checksum_algorithm)
    digest_valid = payload.digest_verified and bool(artifact.digest and artifact.digest_algorithm)
    verified = (
        checksum_valid
        and digest_valid
        and payload.provenance_status == "verified"
        and payload.sbom_status
        in {
            "available",
            "verified",
        }
    )
    evidence_hash = stable_hash(payload.model_dump(mode="json"))
    previous_hash = artifact.metadata_payload.get("verification_evidence_hash")
    if artifact.verified_at and previous_hash != evidence_hash:
        raise ValueError("artifact_verification_conflict")
    artifact.status = "verified" if verified else "failed"
    artifact.provenance_status = payload.provenance_status
    artifact.sbom_status = payload.sbom_status
    artifact.signature_status = payload.signature_status
    artifact.verified_at = _now()
    artifact.metadata_payload = {
        **artifact.metadata_payload,
        "verification_evidence": payload.evidence_payload,
        "verification_evidence_hash": evidence_hash,
        "checksum_verified": payload.checksum_verified,
        "digest_verified": payload.digest_verified,
    }
    db.add(artifact)
    db.flush()
    return artifact


def register_compatibility(
    db: Session, release_id: uuid.UUID, payload: ReleaseCompatibilityCreate
) -> ReleaseCompatibility:
    repository = ReleaseGovernanceRepository(db)
    _require_release(repository, release_id)
    evidence_hash = stable_hash(payload.model_dump(mode="json"))
    for item in repository.list_compatibility(release_id):
        if (
            item.compatibility_type == payload.compatibility_type
            and item.minimum_version == payload.minimum_version
            and item.maximum_version == payload.maximum_version
        ):
            if item.evidence_hash != evidence_hash:
                raise ValueError("compatibility_conflict")
            return item
    record = ReleaseCompatibility(release_id=release_id, **payload.model_dump(), evidence_hash=evidence_hash)
    db.add(record)
    db.flush()
    return record


def register_migration_requirement(
    db: Session, release_id: uuid.UUID, payload: MigrationRequirementCreate
) -> ReleaseMigrationRequirement:
    repository = ReleaseGovernanceRepository(db)
    _require_release(repository, release_id)
    evidence_hash = stable_hash(payload.model_dump(mode="json"))
    for item in repository.list_migration_requirements(release_id):
        if item.from_revision == payload.from_revision and item.to_revision == payload.to_revision:
            if item.evidence_hash != evidence_hash:
                raise ValueError("migration_requirement_conflict")
            return item
    record = ReleaseMigrationRequirement(release_id=release_id, **payload.model_dump(), evidence_hash=evidence_hash)
    db.add(record)
    db.flush()
    return record


def register_rollback_target(
    db: Session, release_id: uuid.UUID, payload: RollbackTargetCreate
) -> ReleaseRollbackTarget:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    target = _require_release(repository, payload.rollback_target_release_id)
    if release.id == target.id:
        raise ValueError("rollback_target_cannot_reference_same_release")
    if release.edition != target.edition:
        raise ValueError("rollback_target_edition_mismatch")
    migrations = repository.list_migration_requirements(release_id)
    if any(not item.reversible for item in migrations) and payload.database_rollback_supported:
        raise ValueError("irreversible_migration_disallows_database_rollback")
    evidence_hash = stable_hash(payload.model_dump(mode="json"))
    existing = repository.get_rollback_target(release_id)
    if existing is not None:
        if existing.evidence_hash != evidence_hash:
            raise ValueError("rollback_target_conflict")
        return existing
    record = ReleaseRollbackTarget(release_id=release_id, **payload.model_dump(), evidence_hash=evidence_hash)
    db.add(record)
    db.flush()
    return record


def _blocker(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "domain": "release_governance"}


def _acceptance_snapshot(repository: ReleaseGovernanceRepository, release: GovernedRelease) -> dict[str, Any]:
    build = repository.latest_build(release.id)
    build_manifest = repository.get_build_manifest(build.id) if build else None
    deployment_manifest = repository.get_deployment_manifest(release.id)
    artifacts = repository.list_artifacts(release.id)
    compatibility = repository.list_compatibility(release.id)
    migrations = repository.list_migration_requirements(release.id)
    rollback = repository.get_rollback_target(release.id)
    required_codes = (
        set((deployment_manifest.manifest_payload or {}).get("required_artifact_codes") or [])
        if deployment_manifest
        else set()
    )
    required_artifacts = [item for item in artifacts if item.required]
    present_codes = {item.artifact_code for item in artifacts}
    required_present = bool(required_codes or required_artifacts) and required_codes.issubset(present_codes)
    required_verified = required_present and all(item.status == "verified" for item in required_artifacts)
    checksums_valid = bool(required_artifacts) and all(
        bool(item.checksum and item.checksum_algorithm and item.metadata_payload.get("checksum_verified"))
        for item in required_artifacts
    )
    digests_valid = bool(required_artifacts) and all(
        bool(item.digest and item.digest_algorithm and item.metadata_payload.get("digest_verified"))
        for item in required_artifacts
    )
    provenance_available = bool(required_artifacts) and all(
        item.provenance_status == "verified" for item in required_artifacts
    )
    sbom_available = bool(required_artifacts) and all(
        item.sbom_status in {"available", "verified"} for item in required_artifacts
    )
    required_compatibility = (
        set((deployment_manifest.manifest_payload or {}).get("required_compatibility_types") or [])
        if deployment_manifest
        else set()
    )
    compatible_types = {item.compatibility_type for item in compatibility if item.compatible}
    required_compatibility_records = [
        item for item in compatibility if item.compatibility_type in required_compatibility
    ]
    compatibility_valid = (
        bool(required_compatibility)
        and required_compatibility.issubset(compatible_types)
        and all(item.compatible for item in required_compatibility_records)
    )
    target_revision = build_manifest.database_schema_revision if build_manifest else None
    migration_valid = (
        bool(migrations) and bool(target_revision) and any(item.to_revision == target_revision for item in migrations)
    )
    rollback_valid = bool(
        rollback
        and rollback.rollback_supported
        and rollback.application_rollback_supported
        and not rollback.blockers
        and rollback.verified_at
    )
    edition_valid = all(item.edition == release.edition for item in artifacts)
    explicit_failures = sorted(
        {
            *(
                "artifact_verification_failed"
                for item in required_artifacts
                if item.status == "failed" or item.provenance_status == "failed" or item.sbom_status == "failed"
            ),
            *(
                "compatibility_explicitly_incompatible"
                for item in required_compatibility_records
                if not item.compatible
            ),
        }
    )
    build_manifest_valid = bool(
        build
        and build.build_status == "completed"
        and build_manifest
        and build_manifest.application_version == release.version
        and build_manifest.source_revision == release.source_revision
    )
    deployment_manifest_valid = bool(
        deployment_manifest
        and build
        and deployment_manifest.build_id == build.id
        and deployment_manifest.configuration_requirements.get("profile")
        and build_manifest
        and deployment_manifest.configuration_requirements.get("profile") == build_manifest.configuration_profile
        and deployment_manifest.rollback_target_release_id
    )
    return {
        "build_id": str(build.id) if build else None,
        "build_manifest_id": str(build_manifest.id) if build_manifest else None,
        "deployment_manifest_id": str(deployment_manifest.id) if deployment_manifest else None,
        "artifact_ids": [str(item.id) for item in artifacts],
        "compatibility_ids": [str(item.id) for item in compatibility],
        "migration_requirement_ids": [str(item.id) for item in migrations],
        "rollback_target_id": str(rollback.id) if rollback else None,
        "build_manifest_valid": build_manifest_valid,
        "deployment_manifest_valid": deployment_manifest_valid,
        "required_artifacts_present": required_present,
        "required_artifacts_verified": required_verified,
        "checksums_valid": checksums_valid,
        "digests_valid": digests_valid,
        "provenance_available": provenance_available,
        "sbom_available": sbom_available,
        "compatibility_valid": compatibility_valid,
        "migration_requirements_valid": migration_valid,
        "rollback_target_valid": rollback_valid,
        "edition_boundary_valid": edition_valid,
        "explicit_failures": explicit_failures,
    }


def evaluate_release_acceptance(db: Session, release_id: uuid.UUID) -> ReleaseAcceptanceEvidence:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    snapshot = _acceptance_snapshot(repository, release)
    checks = {
        key: value
        for key, value in snapshot.items()
        if key.endswith("_valid") or key.endswith("_present") or key.endswith("_verified") or key.endswith("_available")
    }
    blocker_messages = {
        "build_manifest_valid": "A completed build with a valid governed manifest is required.",
        "deployment_manifest_valid": "A governed deployment manifest with configuration and rollback is required.",
        "required_artifacts_present": "Required release artifacts are missing.",
        "required_artifacts_verified": "Required release artifacts are not verified.",
        "checksums_valid": "Required artifact checksum evidence is invalid or missing.",
        "digests_valid": "Required artifact digest evidence is invalid or missing.",
        "provenance_available": "Required artifact provenance is not verified.",
        "sbom_available": "Required artifact SBOM evidence is missing.",
        "compatibility_valid": "Required compatibility evidence is missing or incompatible.",
        "migration_requirements_valid": "Migration requirements do not cover the governed schema revision.",
        "rollback_target_valid": "A verified governed rollback target is required.",
        "edition_boundary_valid": "Artifact editions do not match the governed release edition.",
    }
    blockers = [_blocker(key.upper(), blocker_messages[key]) for key, valid in checks.items() if not valid]
    status = "passed" if not blockers else ("failed" if snapshot.get("explicit_failures") else "blocked")
    evidence_hash = stable_hash(snapshot)
    existing = repository.latest_acceptance(release_id)
    if existing is not None and existing.evidence_hash == evidence_hash:
        return existing
    evaluated_at = _now()
    result_hash = stable_hash(
        {"release_id": release_id, "status": status, "evidence_hash": evidence_hash, "blockers": blockers}
    )
    record = ReleaseAcceptanceEvidence(
        release_id=release_id,
        status=status,
        blockers=blockers,
        warnings=[],
        evidence_payload=snapshot,
        evidence_hash=evidence_hash,
        result_hash=result_hash,
        evaluated_at=evaluated_at,
        **checks,
    )
    db.add(record)
    release.status = "validated" if status == "passed" else "blocked"
    release.result_hash = result_hash
    db.add(release)
    db.flush()
    return record


def get_release_readiness(db: Session, release_id: uuid.UUID) -> ReleaseReadinessResponse:
    repository = ReleaseGovernanceRepository(db)
    release = _require_release(repository, release_id)
    build = repository.latest_build(release_id)
    build_manifest = repository.get_build_manifest(build.id) if build else None
    deployment_manifest = repository.get_deployment_manifest(release_id)
    artifacts = repository.list_artifacts(release_id)
    compatibility = repository.list_compatibility(release_id)
    migrations = repository.list_migration_requirements(release_id)
    rollback = repository.get_rollback_target(release_id)
    acceptance = repository.latest_acceptance(release_id)
    blockers = (
        list(acceptance.blockers)
        if acceptance
        else [_blocker("RELEASE_NOT_EVALUATED", "Release acceptance has not been evaluated.")]
    )
    required = [item for item in artifacts if item.required]
    missing = (
        sorted(
            set((deployment_manifest.manifest_payload or {}).get("required_artifact_codes") or [])
            - {item.artifact_code for item in artifacts}
        )
        if deployment_manifest
        else []
    )
    next_action_map = {
        "build_manifest": build_manifest is None,
        "deployment_manifest": deployment_manifest is None,
        "required_artifact": not artifacts or bool(missing),
        "checksum": any(not item.checksum for item in required),
        "digest": any(not item.digest for item in required),
        "provenance": any(item.provenance_status != "verified" for item in required),
        "sbom": any(item.sbom_status not in {"available", "verified"} for item in required),
        "compatibility": not compatibility,
        "migration_requirements": not migrations,
        "rollback_target": rollback is None,
        "verify_release": acceptance is None or acceptance.status != "passed",
    }
    action_codes = {
        "build_manifest": "register_build_manifest",
        "deployment_manifest": "register_deployment_manifest",
        "required_artifact": "register_required_artifact",
        "checksum": "add_checksum",
        "digest": "add_digest",
        "provenance": "register_provenance",
        "sbom": "register_sbom",
        "compatibility": "define_compatibility",
        "migration_requirements": "define_migration_requirements",
        "rollback_target": "define_rollback_target",
        "verify_release": "verify_release",
    }
    next_actions = [
        {"action": action_codes[key], "reason": key}
        for key, required_action in next_action_map.items()
        if required_action
    ]
    acceptance_fields = (
        "build_manifest_valid",
        "deployment_manifest_valid",
        "required_artifacts_present",
        "required_artifacts_verified",
        "checksums_valid",
        "digests_valid",
        "provenance_available",
        "sbom_available",
        "compatibility_valid",
        "migration_requirements_valid",
        "rollback_target_valid",
        "edition_boundary_valid",
    )
    contract_gates = [
        {
            "gate_code": field,
            "status": "passed"
            if acceptance and getattr(acceptance, field)
            else "blocked"
            if acceptance
            else "not_evaluated",
            "summary": "Persisted release acceptance field {} is {}.".format(
                field,
                "valid"
                if acceptance and getattr(acceptance, field)
                else "not valid"
                if acceptance
                else "not evaluated",
            ),
            "evidence_reference": str(acceptance.id) if acceptance else None,
        }
        for field in acceptance_fields
    ]
    integrity_errors = []
    if acceptance and stable_hash(acceptance.evidence_payload) != acceptance.evidence_hash:
        integrity_errors.append(
            {
                "code": "release_acceptance_evidence_corrupt",
                "message": "Persisted release acceptance evidence hash does not match its payload.",
                "evidence_id": str(acceptance.id),
            }
        )
    evidence_contract = build_readiness_evidence(
        domain="release_governance",
        status=acceptance.status if acceptance else "not_evaluated",
        gate_results=contract_gates,
        blockers=blockers,
        warnings=list(acceptance.warnings) if acceptance else [],
        next_actions=next_actions,
        runtime_version="release-governance-runtime.v1",
        evaluation_timestamp=acceptance.evaluated_at if acceptance else release.created_at,
        expires_at=None,
        evidence_origin="release_governance_runtime",
        components_evaluated=[field.removesuffix("_valid") for field in acceptance_fields],
        evidence_ids=[str(acceptance.id)] if acceptance else [],
        source_contract_version=release.contract_version,
        supported_contract_versions=(CONTRACT_VERSION,),
        source_runtime_version="release-governance-runtime.v1",
        supported_runtime_versions=("release-governance-runtime.v1",),
        integrity_errors=integrity_errors,
    )
    return ReleaseReadinessResponse(
        evidence_contract=evidence_contract,
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        release=release,
        build=build,
        build_manifest=build_manifest,
        deployment_manifest=deployment_manifest,
        artifact_summary={
            "total": len(artifacts),
            "required": len(required),
            "verified": sum(item.status == "verified" for item in required),
            "missing": missing,
        },
        artifacts=artifacts,
        compatibility_summary={
            "total": len(compatibility),
            "compatible": sum(item.compatible for item in compatibility),
            "types": sorted({item.compatibility_type for item in compatibility}),
        },
        migration_summary={
            "total": len(migrations),
            "required": any(item.migration_required for item in migrations),
            "reversible": all(item.reversible for item in migrations) if migrations else None,
            "target_revisions": sorted({item.to_revision for item in migrations}),
        },
        rollback_summary={
            "configured": rollback is not None,
            "target_release_id": rollback.rollback_target_release_id if rollback else None,
            "supported": rollback.rollback_supported if rollback else False,
            "verified_at": rollback.verified_at if rollback else None,
        },
        acceptance=ReleaseAcceptanceRead.model_validate(acceptance) if acceptance else None,
        acceptance_status=evidence_contract.status,
        blockers=evidence_contract.blockers,
        warnings=evidence_contract.warnings,
        recommendations=evidence_contract.recommendations,
        next_actions=evidence_contract.next_actions,
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
    )


def get_latest_release(db: Session, *, edition: str | None = None) -> LatestReleaseResponse:
    release = ReleaseGovernanceRepository(db).latest_release(edition=edition)
    return LatestReleaseResponse(found=release is not None, release=release)


def get_latest_release_readiness(db: Session, *, edition: str | None = None) -> LatestReleaseReadinessResponse:
    release = ReleaseGovernanceRepository(db).latest_release(edition=edition)
    return LatestReleaseReadinessResponse(
        found=release is not None,
        readiness=get_release_readiness(db, release.id) if release else None,
    )
