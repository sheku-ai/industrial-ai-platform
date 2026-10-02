from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

BAD_REQUEST_CODES = {
    "invalid_scope",
    "organization_id_required",
    "invalid_timestamp",
    "invalid_contract_version",
    "invalid_runtime_version",
}
CONFLICT_CODES = {
    "idempotency_key_conflict",
    "portal_evidence_idempotency_conflict",
    "observability_signal_idempotency_conflict",
    "observability_heartbeat_idempotency_conflict",
    "observability_availability_idempotency_conflict",
    "observability_evaluation_idempotency_conflict",
    "release_code_conflict",
    "release_acceptance_required",
    "immutable_build_manifest_conflict",
    "immutable_deployment_manifest_conflict",
    "immutable_artifact_verification_conflict",
    "compatibility_evidence_conflict",
    "migration_evidence_conflict",
    "rollback_evidence_conflict",
    "load_test_not_running",
    "artifact_build_mismatch",
    "artifact_edition_mismatch",
    "build_manifest_release_mismatch",
    "build_manifest_required",
    "build_manifest_timestamp_mismatch",
    "build_source_revision_mismatch",
    "deployment_manifest_build_mismatch",
    "irreversible_migration_disallows_database_rollback",
    "rollback_target_cannot_reference_same_release",
    "rollback_target_edition_mismatch",
    "security_policy_conflict",
}


def runtime_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IntegrityError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="runtime_persistence_conflict",
        )
    if isinstance(exc, SQLAlchemyError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="runtime_persistence_error",
        )
    code = str(exc)
    if isinstance(exc, LookupError) or code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in BAD_REQUEST_CODES:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=code)
    if code in CONFLICT_CODES or code.endswith("_conflict"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="runtime_operation_failed",
    )
