from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.release_governance import ReleaseGovernanceRepository
from app.services.database_revision import resolve_database_revision


def _alembic_state(db: Session) -> dict[str, Any]:
    current = resolve_database_revision(db)
    current_revisions = [part for part in current.split(",") if part]
    return {
        "current_revisions": current_revisions,
        "database_current_revision": current_revisions[0] if len(current_revisions) == 1 else None,
        "database_revision_count": len(current_revisions),
        "source": "postgresql_alembic_version",
    }


def _api_catalog(routes: list[Any]) -> dict[str, Any]:
    principal_routes = sorted(
        {
            str(route.path)
            for route in routes
            if str(getattr(route, "path", "")).startswith(("/api/core", "/api/platform"))
            and getattr(route, "methods", None)
        }
    )
    return {
        "principal_routes": principal_routes,
        "principal_route_count": len(principal_routes),
        "source": "fastapi_registered_routes",
    }


def evaluate_migration_state_evidence(
    *,
    current_revisions: list[str],
    target_revision: str | None,
    migration_requirement: Any | None,
    database_compatibility: list[Any],
    release_id: Any | None,
    build_id: Any | None,
    build_manifest_id: Any | None,
    deployment_build_id: Any | None,
    acceptance_status: str | None,
) -> tuple[bool, dict[str, bool]]:
    evidence = migration_requirement.evidence_payload if migration_requirement else {}
    current_revision = current_revisions[0] if len(current_revisions) == 1 else None
    checks = {
        "database_at_expected_revision": bool(target_revision and current_revisions == [target_revision]),
        "repository_target_matches_build": evidence.get("repository_target_revision") == target_revision,
        "database_evidence_matches_current": evidence.get("database_current_revision") == current_revision,
        "single_alembic_head": evidence.get("single_alembic_head") is True,
        "pending_migrations_zero": evidence.get("pending_migrations_count") == 0,
        "schema_compatible": (
            evidence.get("schema_compatibility_status") == "compatible"
            and bool(database_compatibility)
            and all(item.compatible for item in database_compatibility)
        ),
        "release_correlated": bool(release_id and evidence.get("release_id") == str(release_id)),
        "build_correlated": bool(build_id and evidence.get("build_id") == str(build_id)),
        "build_manifest_correlated": bool(
            build_manifest_id and evidence.get("build_manifest_id") == str(build_manifest_id)
        ),
        "deployment_manifest_correlated": bool(
            deployment_build_id and build_id and deployment_build_id == build_id
        ),
        "migration_requirement_correlated": bool(
            migration_requirement
            and evidence.get("from_revision") == migration_requirement.from_revision
            and evidence.get("to_revision") == migration_requirement.to_revision
        ),
        "release_acceptance_passed": acceptance_status == "passed",
    }
    return bool(migration_requirement and all(checks.values())), checks


def build_production_deployment_projection(
    db: Session,
    *,
    routes: list[Any] | None = None,
) -> dict[str, dict[str, Any]]:
    migration_state = _alembic_state(db)
    repository = ReleaseGovernanceRepository(db)
    release = repository.latest_release()
    build = repository.latest_build(release.id) if release else None
    build_manifest = repository.get_build_manifest(build.id) if build else None
    deployment_manifest = repository.get_deployment_manifest(release.id) if release else None
    acceptance = repository.latest_acceptance(release.id) if release else None
    compatibility = repository.list_compatibility(release.id) if release else []
    migration_requirements = repository.list_migration_requirements(release.id) if release else []
    rollback = repository.get_rollback_target(release.id) if release else None
    artifacts = repository.list_artifacts(release.id) if release else []
    current_revisions = migration_state["current_revisions"]
    target_revision = build_manifest.database_schema_revision if build_manifest else None
    matching_migration = next(
        (item for item in migration_requirements if item.to_revision == target_revision),
        None,
    )
    database_compatibility = [
        item for item in compatibility if item.compatibility_type == "database_schema"
    ]
    migration_evidenced, migration_checks = evaluate_migration_state_evidence(
        current_revisions=current_revisions,
        target_revision=target_revision,
        migration_requirement=matching_migration,
        database_compatibility=database_compatibility,
        release_id=release.id if release else None,
        build_id=build.id if build else None,
        build_manifest_id=build_manifest.id if build_manifest else None,
        deployment_build_id=deployment_manifest.build_id if deployment_manifest else None,
        acceptance_status=acceptance.status if acceptance else None,
    )
    upgrade_evidenced = bool(
        compatibility and migration_requirements and all(item.compatible for item in compatibility)
    )
    rollback_evidenced = bool(
        rollback
        and rollback.rollback_supported
        and rollback.application_rollback_supported
        and rollback.verified_at
        and not rollback.blockers
    )
    artifacts_evidenced = bool(
        acceptance
        and acceptance.required_artifacts_present
        and acceptance.required_artifacts_verified
        and acceptance.checksums_valid
        and acceptance.digests_valid
        and acceptance.provenance_available
        and acceptance.sbom_available
    )
    deployment_evidenced = bool(acceptance and acceptance.deployment_manifest_valid and deployment_manifest)
    return {
        "migration_state": {
            **migration_state,
            "status": "passed" if migration_evidenced else "blocked",
            "clean": migration_evidenced,
            "governed_release_id": str(release.id) if release else None,
            "governed_build_id": str(build.id) if build else None,
            "build_manifest_id": str(build_manifest.id) if build_manifest else None,
            "target_revision": target_revision,
            "migration_requirement_id": str(matching_migration.id) if matching_migration else None,
            "migration_checks": migration_checks,
            "repository_target_revision": (
                matching_migration.evidence_payload.get("repository_target_revision")
                if matching_migration
                else None
            ),
            "single_alembic_head": (
                matching_migration.evidence_payload.get("single_alembic_head")
                if matching_migration
                else None
            ),
            "pending_migrations_count": (
                matching_migration.evidence_payload.get("pending_migrations_count")
                if matching_migration
                else None
            ),
            "schema_compatibility_status": (
                matching_migration.evidence_payload.get("schema_compatibility_status")
                if matching_migration
                else None
            ),
            "evidence_hash": matching_migration.evidence_hash if matching_migration else None,
            "source": "postgresql_release_governance_and_alembic_version",
        },
        "upgrade_path": {
            "status": "passed" if upgrade_evidenced else "blocked",
            "compatibility_evidence_ids": [str(item.id) for item in compatibility],
            "migration_requirement_ids": [str(item.id) for item in migration_requirements],
            "target_revision": target_revision,
            "source": "postgresql_release_compatibility_and_migration_requirements",
        },
        "rollback_target": {
            "status": "passed" if rollback_evidenced else "blocked",
            "rollback_target_id": str(rollback.id) if rollback else None,
            "rollback_target_release_id": str(rollback.rollback_target_release_id) if rollback else None,
            "database_rollback_supported": rollback.database_rollback_supported if rollback else False,
            "application_rollback_supported": rollback.application_rollback_supported if rollback else False,
            "source": "postgresql_release_rollback_target",
        },
        "release_artifacts": {
            "status": "passed" if artifacts_evidenced else "blocked",
            "release_id": str(release.id) if release else None,
            "application_version": release.version if release else None,
            "source_revision": release.source_revision if release else None,
            "build_timestamp": build.build_timestamp.isoformat() if build else None,
            "artifact_ids": [str(item.id) for item in artifacts],
            "acceptance_evidence_id": str(acceptance.id) if acceptance else None,
            "source": "postgresql_release_governance",
        },
        "deployment_manifest": {
            "status": "passed" if deployment_evidenced else "blocked",
            "release_id": str(release.id) if release else None,
            "manifest_id": str(deployment_manifest.id) if deployment_manifest else None,
            "manifest_hash": deployment_manifest.manifest_hash if deployment_manifest else None,
            "configuration_profile": (
                deployment_manifest.configuration_requirements.get("profile") if deployment_manifest else None
            ),
            "configuration_requirements": deployment_manifest.configuration_requirements if deployment_manifest else {},
            "evaluated_at": datetime.now(UTC).isoformat(),
            "source": "postgresql_release_deployment_manifest",
        },
        "build_manifest": {
            "status": "passed" if build_manifest else "blocked",
            "manifest_id": str(build_manifest.id) if build_manifest else None,
            "database_revision": target_revision,
            "application_version": build_manifest.application_version if build_manifest else None,
            "source_revision": build_manifest.source_revision if build_manifest else None,
            "source": "postgresql_release_build_manifest",
        },
        "api_catalog": _api_catalog(list(routes or [])),
    }
