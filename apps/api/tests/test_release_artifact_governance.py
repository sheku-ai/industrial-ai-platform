from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.routes.release_governance import _authorize
from app.models.release_governance import GovernedRelease, ReleaseArtifact
from app.schemas.release_governance import (
    BuildManifestCreate,
    MigrationRequirementCreate,
    ReleaseArtifactCreate,
    mask_artifact_location,
    reject_secrets,
)
from app.services import production_deployment_projection, release_governance_runtime


class _Db:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def _release(**overrides):
    values = {
        "id": uuid.uuid4(),
        "release_code": "platform-1.4.0-rc1",
        "version": "1.4.0-rc1",
        "edition": "community",
        "channel": "release_candidate",
        "status": "draft",
        "source_repository": "generic/platform",
        "source_revision": "revision-123",
        "source_branch": "main",
        "created_by": "operator",
        "contract_version": "release_artifact_governance.v1",
        "idempotency_key": "release-key",
        "input_hash": "a" * 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _build(release_id, **overrides):
    values = {
        "id": uuid.uuid4(),
        "release_id": release_id,
        "build_number": "1",
        "build_status": "completed",
        "build_timestamp": datetime(2026, 7, 14, tzinfo=UTC),
        "source_revision": "revision-123",
        "target_platform": "container",
        "target_architecture": "multi_arch",
        "build_profile": "production",
        "reproducible": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_create_governed_release_and_reuse_identical_idempotency(monkeypatch) -> None:
    created = None

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release_by_idempotency(self, key):
            return created

        def list_releases_by_logical_identity(self, **identity):
            return []

        def get_release_by_code(self, code):
            return None

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    db = _Db()
    payload = release_governance_runtime.GovernedReleaseCreate(
        release_code="platform-1.4.0-rc1",
        version="1.4.0-rc1",
        edition="community",
        channel="release_candidate",
        source_repository="generic/platform",
        source_revision="revision-123",
        idempotency_key="release-key",
    )
    first = release_governance_runtime.create_release(db, payload)
    created = first
    second = release_governance_runtime.create_release(db, payload)

    assert isinstance(first, GovernedRelease)
    assert second is first
    assert len(db.added) == 1
    assert first.release_code == release_governance_runtime.governed_release_code(payload)
    assert first.idempotency_key == release_governance_runtime.governed_release_idempotency_key(payload)
    assert first.input_hash == release_governance_runtime.governed_release_identity_hash(payload)


def test_release_idempotency_conflicts_when_input_changes(monkeypatch) -> None:
    existing = _release(input_hash="f" * 64)

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release_by_idempotency(self, key):
            return existing

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    payload = release_governance_runtime.GovernedReleaseCreate(
        release_code="platform-1.4.0-rc1",
        version="1.4.0-rc1",
        edition="community",
        channel="release_candidate",
        source_repository="generic/platform",
        source_revision="revision-123",
        idempotency_key="release-key",
    )

    with pytest.raises(ValueError, match="idempotency_key_conflict"):
        release_governance_runtime.create_release(_Db(), payload)


def test_release_code_has_database_uniqueness_contract() -> None:
    constraints = {item.name for item in GovernedRelease.__table__.constraints}
    assert "uq_runtime_governed_releases_code" in constraints


@pytest.mark.parametrize(
    ("version", "channel", "source_revision"),
    [
        ("1.3.1", "stable", "baseline-controlled-release-evidence"),
        ("1.3.2-rc.1", "release_candidate", "controlled-release-evidence"),
    ],
)
def test_logical_release_replay_reuses_canonical_legacy_row_without_increasing_count(
    monkeypatch, version, channel, source_revision
) -> None:
    canonical = _release(
        version=version,
        channel=channel,
        source_revision=source_revision,
        idempotency_key="legacy-temporal-key",
        release_code="legacy-temporal-code",
    )

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release_by_idempotency(self, key):
            return None

        def list_releases_by_logical_identity(self, **identity):
            return [canonical]

        def get_release_by_code(self, code):
            return None

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    payload = release_governance_runtime.GovernedReleaseCreate(
        release_code="variable-client-code",
        version=version,
        edition="community",
        channel=channel,
        source_repository="generic/platform",
        source_revision=source_revision,
        source_branch="main",
        idempotency_key="variable-client-key",
    )
    db = _Db()

    first = release_governance_runtime.create_release(db, payload)
    second = release_governance_runtime.create_release(db, payload)

    assert first.id == canonical.id
    assert second.id == canonical.id
    assert db.added == []


def test_logical_release_source_branch_change_conflicts(monkeypatch) -> None:
    existing = _release(source_branch="main")

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release_by_idempotency(self, key):
            return existing

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    payload = release_governance_runtime.GovernedReleaseCreate(
        release_code="ignored",
        version=existing.version,
        edition=existing.edition,
        channel=existing.channel,
        source_repository=existing.source_repository,
        source_revision=existing.source_revision,
        source_branch="release/other",
        idempotency_key="ignored",
    )

    with pytest.raises(ValueError, match="idempotency_key_conflict"):
        release_governance_runtime.create_release(_Db(), payload)


def test_governed_release_identity_isolated_by_edition() -> None:
    community = release_governance_runtime.GovernedReleaseCreate(
        release_code="ignored-community",
        version="1.3.2-rc.1",
        edition="community",
        channel="release_candidate",
        source_repository="generic/platform",
        source_revision="revision-123",
        idempotency_key="ignored-community",
    )
    enterprise = community.model_copy(
        update={
            "release_code": "ignored-enterprise",
            "edition": "enterprise",
            "idempotency_key": "ignored-enterprise",
        }
    )

    assert release_governance_runtime.governed_release_identity_hash(community) != (
        release_governance_runtime.governed_release_identity_hash(enterprise)
    )
    assert release_governance_runtime.governed_release_idempotency_key(community) != (
        release_governance_runtime.governed_release_idempotency_key(enterprise)
    )


def test_build_completion_requires_persisted_manifest(monkeypatch) -> None:
    build = _build(uuid.uuid4(), build_status="planned")

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_build(self, build_id):
            return build

        def get_build_manifest(self, build_id):
            return None

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)

    with pytest.raises(ValueError, match="build_manifest_required"):
        release_governance_runtime.complete_build(_Db(), build.id, release_governance_runtime.ReleaseBuildComplete())


def test_build_idempotency_reuses_same_persisted_input(monkeypatch) -> None:
    release = _release()
    existing = None

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release(self, release_id):
            return release

        def get_build_by_idempotency(self, release_id, key):
            return existing

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    payload = release_governance_runtime.ReleaseBuildCreate(
        build_number="1",
        build_timestamp=datetime(2026, 7, 14, tzinfo=UTC),
        builder_type="manual_evidence",
        source_revision=release.source_revision,
        target_platform="container",
        target_architecture="multi_arch",
        build_profile="production",
        idempotency_key="build-key",
    )
    db = _Db()
    first = release_governance_runtime.create_build(db, release.id, payload)
    existing = first
    second = release_governance_runtime.create_build(db, release.id, payload)
    assert second is first


def test_manifest_hashing_is_deterministic_and_structured() -> None:
    left = {"components": {"api": "1", "portal": "1"}, "revision": "920"}
    right = {"revision": "920", "components": {"portal": "1", "api": "1"}}
    assert release_governance_runtime.stable_hash(left) == release_governance_runtime.stable_hash(right)


def test_build_and_deployment_manifests_share_deterministic_hash_contract() -> None:
    build_manifest = {"manifest_version": "1", "application_version": "1.4.0", "components": ["api", "portal"]}
    deployment_manifest = {"manifest_version": "1", "required_services": ["api", "portal"], "profile": "production"}
    assert len(release_governance_runtime.stable_hash(build_manifest)) == 64
    assert len(release_governance_runtime.stable_hash(deployment_manifest)) == 64
    assert release_governance_runtime.stable_hash(build_manifest) != release_governance_runtime.stable_hash(
        deployment_manifest
    )


def test_build_manifest_requires_all_product_components() -> None:
    with pytest.raises(ValidationError, match="required component versions missing"):
        BuildManifestCreate(
            manifest_version="1",
            application_version="1.4.0",
            source_revision="revision-123",
            build_timestamp=datetime.now(UTC),
            database_schema_revision="20260714_920",
            target_platforms=["container"],
            target_architectures=["amd64"],
            component_versions={"api": "1.4.0"},
            configuration_profile="production",
        )


def test_required_artifact_needs_checksum_or_digest() -> None:
    with pytest.raises(ValidationError, match="checksum or digest"):
        ReleaseArtifactCreate(
            build_id=uuid.uuid4(),
            artifact_code="api-image",
            artifact_type="container_image",
            component="api",
            edition="community",
            platform="container",
            architecture="amd64",
            media_type="application/vnd.oci.image.manifest.v1+json",
            artifact_reference="logical:api-image",
            required=True,
        )


def test_artifact_reference_is_masked_and_secret_payload_rejected() -> None:
    assert mask_artifact_location("https://user:secret@example.invalid/path") == "https://example.invalid/path"
    with pytest.raises(ValueError, match="secret material"):
        reject_secrets({"nested": {"password": "do-not-store"}})


def test_artifact_edition_must_match_release(monkeypatch) -> None:
    release = _release(edition="community")
    build = _build(release.id)

    class Repository:
        def __init__(self, db) -> None:
            pass

        def get_release(self, release_id):
            return release

        def get_build(self, build_id):
            return build

    monkeypatch.setattr(release_governance_runtime, "ReleaseGovernanceRepository", Repository)
    payload = ReleaseArtifactCreate(
        build_id=build.id,
        artifact_code="enterprise-api",
        artifact_type="container_image",
        component="api",
        edition="enterprise",
        platform="container",
        architecture="amd64",
        media_type="application/vnd.oci.image.manifest.v1+json",
        artifact_reference="logical:enterprise-api",
        checksum_algorithm="sha256",
        checksum="a" * 64,
    )

    with pytest.raises(ValueError, match="artifact_edition_mismatch"):
        release_governance_runtime.register_artifact(_Db(), release.id, payload)


def test_irreversible_migration_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="requires a reason"):
        MigrationRequirementCreate(
            from_revision="910",
            to_revision="920",
            migration_required=True,
            migration_strategy="forward_only",
            reversible=False,
            evidence_payload={"source": "alembic"},
        )


def test_rollback_target_cannot_reference_same_release() -> None:
    constraints = {item.name for item in release_governance_runtime.ReleaseRollbackTarget.__table__.constraints}
    assert "ck_runtime_release_rollback_not_self" in constraints


def _acceptance_repository(complete: bool):
    release = _release()
    build = _build(release.id)
    manifest = SimpleNamespace(
        id=uuid.uuid4(),
        application_version=release.version,
        source_revision=release.source_revision,
        database_schema_revision="920",
        configuration_profile="production",
    )
    deployment = SimpleNamespace(
        id=uuid.uuid4(),
        build_id=build.id,
        manifest_hash="d" * 64,
        configuration_requirements={"profile": "production"},
        rollback_target_release_id=uuid.uuid4(),
        manifest_payload={
            "required_artifact_codes": ["api-image"],
            "required_compatibility_types": ["database_schema", "previous_release"],
        },
    )
    artifact = SimpleNamespace(
        id=uuid.uuid4(),
        artifact_code="api-image",
        required=True,
        status="verified" if complete else "missing",
        checksum="a" * 64,
        checksum_algorithm="sha256",
        digest="sha256:" + "a" * 64,
        digest_algorithm="sha256",
        provenance_status="verified",
        sbom_status="available",
        edition=release.edition,
        metadata_payload={"checksum_verified": True, "digest_verified": True},
    )
    compatibility = (
        [
            SimpleNamespace(id=uuid.uuid4(), compatibility_type="database_schema", compatible=True),
            SimpleNamespace(id=uuid.uuid4(), compatibility_type="previous_release", compatible=True),
        ]
        if complete
        else []
    )
    migration = (
        [
            SimpleNamespace(
                id=uuid.uuid4(),
                from_revision="910",
                to_revision="920",
                migration_required=True,
                reversible=False,
                evidence_hash="e" * 64,
                evidence_payload={
                    "repository_target_revision": "920",
                    "database_current_revision": "920",
                    "single_alembic_head": True,
                    "pending_migrations_count": 0,
                    "schema_compatibility_status": "compatible",
                    "release_id": str(release.id),
                    "build_id": str(build.id),
                    "build_manifest_id": str(manifest.id),
                    "from_revision": "910",
                    "to_revision": "920",
                },
            )
        ]
        if complete
        else []
    )
    rollback = (
        SimpleNamespace(
            id=uuid.uuid4(),
            rollback_supported=True,
            application_rollback_supported=True,
            database_rollback_supported=False,
            blockers=[],
            verified_at=datetime.now(UTC),
            rollback_target_release_id=uuid.uuid4(),
        )
        if complete
        else None
    )
    return SimpleNamespace(
        latest_build=lambda release_id: build,
        get_build_manifest=lambda build_id: manifest,
        get_deployment_manifest=lambda release_id: deployment,
        list_artifacts=lambda release_id: [artifact],
        list_compatibility=lambda release_id: compatibility,
        list_migration_requirements=lambda release_id: migration,
        get_rollback_target=lambda release_id: rollback,
    ), release


def test_release_acceptance_blocks_without_artifacts_compatibility_migration_and_rollback() -> None:
    repository, release = _acceptance_repository(False)
    snapshot = release_governance_runtime._acceptance_snapshot(repository, release)
    assert snapshot["required_artifacts_verified"] is False
    assert snapshot["compatibility_valid"] is False
    assert snapshot["migration_requirements_valid"] is False
    assert snapshot["rollback_target_valid"] is False


def test_release_acceptance_passes_with_complete_governed_evidence() -> None:
    repository, release = _acceptance_repository(True)
    snapshot = release_governance_runtime._acceptance_snapshot(repository, release)
    checks = [
        value for key, value in snapshot.items() if key.endswith(("_valid", "_present", "_verified", "_available"))
    ]
    assert all(checks)


def test_platform_scope_and_permission_are_enforced() -> None:
    with pytest.raises(Exception, match="platform authorization scope"):
        _authorize(RuntimeRequestContext("organization", uuid.uuid4(), "actor", frozenset()), "read")
    with pytest.raises(Exception, match="permission is required"):
        _authorize(RuntimeRequestContext("platform", None, "actor", frozenset()), "read")
    _authorize(
        RuntimeRequestContext("platform", None, "actor", frozenset({"platform.release_governance:read"})),
        "read",
    )


def test_deployment_projection_consumes_postgresql_release_governance(monkeypatch) -> None:
    repository, release = _acceptance_repository(True)
    acceptance = SimpleNamespace(
        id=uuid.uuid4(),
        required_artifacts_present=True,
        required_artifacts_verified=True,
        checksums_valid=True,
        digests_valid=True,
        provenance_available=True,
        sbom_available=True,
        deployment_manifest_valid=True,
        status="passed",
    )
    repository.latest_release = lambda: release
    repository.latest_acceptance = lambda release_id: acceptance
    repository.get_release = lambda release_id: release

    class RepositoryFactory:
        def __new__(cls, db):
            return repository

    monkeypatch.setattr(production_deployment_projection, "ReleaseGovernanceRepository", RepositoryFactory)
    monkeypatch.setattr(
        production_deployment_projection,
        "_alembic_state",
        lambda db: {
            "current_revisions": ["920"],
            "database_current_revision": "920",
            "database_revision_count": 1,
            "source": "postgresql_alembic_version",
        },
    )
    projection = production_deployment_projection.build_production_deployment_projection(SimpleNamespace())
    assert projection["release_artifacts"]["source"] == "postgresql_release_governance"
    assert projection["deployment_manifest"]["status"] == "passed"
    assert projection["release_artifacts"]["status"] == "passed"
    assert "llm_used" not in projection


def test_release_artifact_model_never_contains_binary_payload() -> None:
    assert "payload" not in ReleaseArtifact.__table__.columns
    assert "binary" not in ReleaseArtifact.__table__.columns
