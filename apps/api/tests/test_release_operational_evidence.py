from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.release_operational_evidence import OperationalEvidenceRequest
from app.services import release_operational_evidence_runtime as runtime


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid.uuid4()
        if getattr(value, "created_at", None) is None:
            value.created_at = datetime.now(UTC)
        self.added.append(value)

    def flush(self) -> None:
        return None


def _request(**overrides: object) -> OperationalEvidenceRequest:
    values: dict[str, object] = {
        "scope": "platform",
        "release_version": "1.4.0-rc.1",
        "alembic_revision": "20260716_980",
        "edition": "community",
        "correlation_id": "correlation-1",
    }
    values.update(overrides)
    if "execution_key" not in values:
        values["execution_key"] = runtime.build_operational_execution_key(
            "rc_operational_refresh",
            str(values["edition"]),
            str(values["release_version"]),
            "rc-refresh",
        )
    return OperationalEvidenceRequest(**values)


def _source(source_type: str, **overrides: object) -> runtime._ResolvedRcSource:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "evidence_type": source_type,
        "status": "passed",
        "scope": "platform",
        "organization_id": None,
        "evaluated_at": now,
        "expires_at": now + timedelta(minutes=10),
        "evidence_hash": "a" * 64,
        "backup_execution_id": uuid.uuid4() if source_type == "backup_execution_completed" else None,
    }
    values.update(overrides)
    return runtime._ResolvedRcSource(**values)


def _sources() -> dict[str, runtime._ResolvedRcSource]:
    return {
        item.id: item
        for item in (
            _source("configuration_preflight"),
            _source("backup_execution_completed"),
            _source("observability_health_evaluation"),
            _source("production_acceptance_run"),
            _source("upgrade_readiness"),
            _source("rollback_eligibility", status="requires_restore"),
        )
    }


def _runtime_with_sources(
    monkeypatch,
    sources: dict[str, runtime._ResolvedRcSource],
    edition: str = "community",
):
    existing: object | None = None

    class Repository:
        def __init__(self, db) -> None:
            pass

        def find_execution(self, **kwargs):
            return existing

    def set_existing(value: object) -> None:
        nonlocal existing
        existing = value

    monkeypatch.setattr(runtime, "ReleaseOperationalEvidenceRepository", Repository)
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition=edition))
    monkeypatch.setattr(
        runtime,
        "_resolve_rc_source",
        lambda db, source_id, request: sources[str(source_id)],
    )
    return set_existing


def _persist(monkeypatch, sources: dict[str, runtime._ResolvedRcSource], **overrides: object):
    set_existing = _runtime_with_sources(monkeypatch, sources)
    db = _Db()
    result = runtime.persist_operational_refresh_summary(
        db,
        _request(**overrides),
        {"client_status": "passed"},
        list(sources),
    )
    return db, result, set_existing


def test_rc_refresh_uses_all_current_persisted_sources(monkeypatch) -> None:
    sources = _sources()
    db, result, _ = _persist(monkeypatch, sources)

    assert result.status == "passed"
    assert result.expires_at == min(source.expires_at for source in sources.values())
    assert result.evidence_payload["client_summary_ignored"] is True
    assert {
        item["evidence_type"] for item in result.evidence_payload["resolved_sources"]
    } == runtime.RC_REFRESH_REQUIRED_SOURCE_TYPES
    assert db.added[0].edition == "community"


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda sources: sources.pop(next(iter(sources))), "rc_refresh_required_source_missing"),
        (
            lambda sources: sources.update(
                {
                    next(iter(sources)): _source(
                        "configuration_preflight", status="failed", id=next(iter(sources))
                    )
                }
            ),
            "rc_refresh_source_status_not_accepted",
        ),
        (
            lambda sources: sources.update(
                {
                    next(iter(sources)): _source(
                        "configuration_preflight",
                        id=next(iter(sources)),
                        expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                }
            ),
            "rc_refresh_source_expired",
        ),
        (
            lambda sources: sources.update(
                {
                    next(iter(sources)): _source(
                        "configuration_preflight", id=next(iter(sources)), scope="organization"
                    )
                }
            ),
            "rc_refresh_source_scope_mismatch",
        ),
    ],
)
def test_rc_refresh_blocks_invalid_authoritative_sources(monkeypatch, mutator, expected_code) -> None:
    sources = _sources()
    mutator(sources)
    _, result, _ = _persist(monkeypatch, sources)

    assert result.status == "blocked"
    assert expected_code in {item["code"] for item in result.evidence_payload["blockers"]}


def test_rc_refresh_blocks_unresolvable_source(monkeypatch) -> None:
    sources = _sources()
    missing_id = str(uuid.uuid4())
    set_existing = _runtime_with_sources(monkeypatch, sources)
    db = _Db()

    def resolve(db, source_id, request):
        if str(source_id) == missing_id:
            raise ValueError("rc_refresh_source_not_found")
        return sources[str(source_id)]

    monkeypatch.setattr(runtime, "_resolve_rc_source", resolve)
    result = runtime.persist_operational_refresh_summary(
        db,
        _request(),
        {"client_status": "passed"},
        [*sources, missing_id],
    )

    assert set_existing is not None
    assert result.status == "blocked"
    assert "rc_refresh_source_not_found" in {item["code"] for item in result.evidence_payload["blockers"]}


def test_rc_refresh_blocks_source_from_another_organization(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    sources = {
        source_id: replace(source, scope="organization", organization_id=organization_id)
        for source_id, source in _sources().items()
    }
    source_id = next(iter(sources))
    sources[source_id] = replace(sources[source_id], organization_id=uuid.uuid4())
    _runtime_with_sources(monkeypatch, sources)

    result = runtime.persist_operational_refresh_summary(
        _Db(),
        _request(scope="organization", organization_id=organization_id),
        {},
        list(sources),
    )

    assert result.status == "blocked"
    assert "rc_refresh_source_organization_mismatch" in {
        item["code"] for item in result.evidence_payload["blockers"]
    }


def test_rc_refresh_replay_uses_authoritative_lineage_and_conflicts_when_it_changes(monkeypatch) -> None:
    sources = _sources()
    db, first, set_existing = _persist(monkeypatch, sources)
    set_existing(db.added[0])

    replay = runtime.persist_operational_refresh_summary(
        db,
        _request(),
        {"client_status": "failed"},
        list(reversed(list(sources))),
    )
    assert replay.id == first.id

    replacement = _source("configuration_preflight")
    changed_sources = {**sources}
    original_id = next(
        source_id for source_id, source in sources.items() if source.evidence_type == "configuration_preflight"
    )
    changed_sources.pop(original_id)
    changed_sources[replacement.id] = replacement
    monkeypatch.setattr(
        runtime,
        "_resolve_rc_source",
        lambda db, source_id, request: changed_sources[str(source_id)],
    )
    with pytest.raises(ValueError, match="idempotency_key_conflict"):
        runtime.persist_operational_refresh_summary(
            db,
            _request(),
            {},
            list(changed_sources),
        )


def test_release_manifest_edition_resolution_is_fail_closed(monkeypatch) -> None:
    base = {
        "version": "1.4.0-rc.1",
        "alembic_head": "20260716_980",
        "supported_editions": ["community", "enterprise"],
        "edition_manifest": {
            "edition": "enterprise",
            "version": "1.4.0-rc.1",
            "alembic_head": "20260716_980",
            "ai_required": False,
            "enterprise_dependency_required": True,
        },
    }
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition="enterprise"))

    assert runtime.resolve_release_manifest_edition(base, "enterprise") == "enterprise"
    with pytest.raises(ValueError, match="release_edition_mismatch"):
        runtime.resolve_release_manifest_edition(base, "community")
    with pytest.raises(ValueError, match="release_manifest_base_edition_forbidden"):
        runtime.resolve_release_manifest_edition({**base, "edition": "community"}, "enterprise")

    community = {
        **base,
        "edition_manifest": {
            **base["edition_manifest"],
            "edition": "community",
            "enterprise_dependency_required": False,
        },
    }
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition="community"))
    assert runtime.resolve_release_manifest_edition(community, "community") == "community"

    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition="unsupported"))
    with pytest.raises(ValueError, match="unsupported_platform_edition"):
        runtime.resolve_release_manifest_edition(community, None)


def test_rc_refresh_persists_the_effective_enterprise_edition(monkeypatch) -> None:
    sources = _sources()
    _runtime_with_sources(monkeypatch, sources, edition="enterprise")
    db = _Db()

    result = runtime.persist_operational_refresh_summary(
        db,
        _request(edition="enterprise"),
        {},
        list(sources),
    )

    assert result.edition == "enterprise"
    assert db.added[0].edition == "enterprise"


def test_operational_execution_keys_are_partitioned_by_edition(monkeypatch) -> None:
    community = runtime.build_operational_execution_key(
        "upgrade_readiness", "community", "1.4.0-rc.1", "backup-1"
    )
    enterprise = runtime.build_operational_execution_key(
        "upgrade_readiness", "enterprise", "1.4.0-rc.1", "backup-1"
    )

    assert community == "upgrade:community:1.4.0-rc.1:backup-1"
    assert enterprise == "upgrade:enterprise:1.4.0-rc.1:backup-1"
    assert community != enterprise

    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition="community"))
    with pytest.raises(ValueError, match="operational_execution_key_edition_required"):
        runtime._validate_operational_execution_key(
            "upgrade_readiness", "community", "1.4.0-rc.1", "upgrade:1.4.0-rc.1:backup-1"
        )


def test_operational_key_replays_are_edition_scoped_and_conflict_safe(monkeypatch) -> None:
    rows: dict[str, object] = {}
    active_edition = "community"

    class Repository:
        def __init__(self, db) -> None:
            pass

        def find_execution(self, **kwargs):
            return rows.get(kwargs["execution_key"])

    monkeypatch.setattr(runtime, "ReleaseOperationalEvidenceRepository", Repository)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(platform_edition=active_edition),
    )
    db = _Db()
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    community_request = _request(
        execution_key="upgrade:community:1.4.0-rc.1:backup-1",
    )
    community = runtime._persist(
        db,
        request=community_request,
        evidence_type="upgrade_readiness",
        status="blocked",
        payload={"source": "community"},
        source_evidence_ids=[],
        expires_at=expires_at,
    )
    rows[community.execution_key] = db.added[-1]

    assert runtime._persist(
        db,
        request=community_request,
        evidence_type="upgrade_readiness",
        status="blocked",
        payload={"source": "community"},
        source_evidence_ids=[],
        expires_at=expires_at,
    ).id == community.id
    with pytest.raises(ValueError, match="idempotency_key_conflict"):
        runtime._persist(
            db,
            request=community_request,
            evidence_type="upgrade_readiness",
            status="blocked",
            payload={"source": "changed"},
            source_evidence_ids=[],
            expires_at=expires_at,
        )

    active_edition = "enterprise"
    enterprise_request = _request(
        edition="enterprise",
        execution_key="upgrade:enterprise:1.4.0-rc.1:backup-1",
    )
    enterprise = runtime._persist(
        db,
        request=enterprise_request,
        evidence_type="upgrade_readiness",
        status="blocked",
        payload={"source": "enterprise"},
        source_evidence_ids=[],
        expires_at=expires_at,
    )

    assert enterprise.id != community.id
    assert enterprise.edition == "enterprise"
    assert enterprise.input_hash != community.input_hash


def test_upgrade_to_the_same_version_remains_blocked(monkeypatch) -> None:
    backup_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    class EvidenceRepository:
        def __init__(self, db) -> None:
            pass

        def find_execution(self, **kwargs):
            return None

    class GovernanceRepository:
        def __init__(self, db) -> None:
            pass

        def list_releases(self, **kwargs):
            return []

    monkeypatch.setattr(runtime, "ReleaseOperationalEvidenceRepository", EvidenceRepository)
    monkeypatch.setattr(runtime, "ReleaseGovernanceRepository", GovernanceRepository)
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(platform_edition="community"))
    monkeypatch.setattr(
        runtime,
        "get_backup_evidence_contract",
        lambda *args, **kwargs: SimpleNamespace(
            evidence_id=uuid.uuid4(),
            backup_id=backup_id,
            status="passed",
            integrity_verified=True,
            application_version="1.4.0-rc.1",
            alembic_revision="20260716_980",
            postgresql_version="16.1",
            expires_at=expires_at,
        ),
    )
    manifest = {
        "version": "1.4.0-rc.1",
        "alembic_head": "20260716_980",
        "supported_editions": ["community", "enterprise"],
        "upgrade_from": ["1.3.1"],
        "repository_heads": ["20260716_980"],
        "supported_postgresql_version": "16",
        "edition_manifest": {
            "edition": "community",
            "version": "1.4.0-rc.1",
            "alembic_head": "20260716_980",
            "ai_required": False,
            "enterprise_dependency_required": False,
        },
    }
    result = runtime.evaluate_upgrade_readiness(
        _Db(),
        _request(
            backup_evidence_id=backup_id,
            execution_key="upgrade:community:1.4.0-rc.1:backup-1",
        ),
        manifest,
    )

    assert result.status == "blocked"
    assert result.evidence_payload["checks"]["backup_revision_matches_source"] is False
    assert result.evidence_payload["checks"]["backup_version_allowed"] is False


def test_release_wrappers_resolve_the_api_interpreter_without_external_pythonpath() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative_path in (
        "scripts/validate_upgrade_readiness.sh",
        "scripts/validate_rollback_eligibility.sh",
        "scripts/validate_rc_packaging.sh",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in content
        assert ".venv/bin/python" in content
    for relative_path in (
        "scripts/validate_upgrade_readiness.sh",
        "scripts/validate_rollback_eligibility.sh",
    ):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "PYTHONPATH=\"${API_DIR}${PYTHONPATH:+:${PYTHONPATH}}\"" in content
