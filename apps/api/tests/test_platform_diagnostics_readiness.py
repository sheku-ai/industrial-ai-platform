from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import platform_diagnostics, platform_release_candidate


def test_filesystem_object_storage_does_not_require_s3_configuration() -> None:
    check = platform_diagnostics.build_object_storage_check({})

    assert check["ready"] is True
    assert check["provider"] == {
        "name": "OBJECT_STORAGE_PROVIDER",
        "value": "filesystem",
        "source": "default",
        "valid": True,
        "issues": [],
    }
    assert [item["name"] for item in check["required_configuration"]] == [
        "INDUSTRIAL_AI_STORAGE_FILESYSTEM_ROOT"
    ]


def test_s3_object_storage_requires_its_authoritative_configuration() -> None:
    incomplete = platform_diagnostics.build_object_storage_check(
        {"OBJECT_STORAGE_PROVIDER": "s3"}
    )
    complete = platform_diagnostics.build_object_storage_check(
        {
            "OBJECT_STORAGE_PROVIDER": "s3",
            "OBJECT_STORAGE_ENDPOINT_URL": "https://storage.internal",
            "OBJECT_STORAGE_ACCESS_KEY": "access-key",
            "OBJECT_STORAGE_SECRET_KEY": "secret-key",
            "OBJECT_STORAGE_BUCKET": "documents",
        }
    )

    assert incomplete["ready"] is False
    assert complete["ready"] is True
    secrets = {
        item["name"]: item["value"]
        for item in complete["required_configuration"]
        if item["name"].endswith(("_ACCESS_KEY", "_SECRET_KEY"))
    }
    assert secrets == {
        "OBJECT_STORAGE_ACCESS_KEY": "<redacted>",
        "OBJECT_STORAGE_SECRET_KEY": "<redacted>",
    }


def test_alembic_receives_database_url_from_dotenv_without_mutating_process(
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="20260923_2830 (head)\n", stderr="")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        platform_diagnostics,
        "load_dotenv_values",
        lambda root: {"DATABASE_URL": "postgresql+psycopg://configured"},
    )
    monkeypatch.setattr(platform_diagnostics.subprocess, "run", fake_run)

    revisions, error = platform_diagnostics.run_alembic(
        Path("/tmp/alembic.ini"),
        "heads",
        (),
        5,
    )

    assert revisions == ["20260923_2830"]
    assert error is None
    assert captured["env"]["DATABASE_URL"] == "postgresql+psycopg://configured"


def test_read_platform_metadata_uses_current_typed_release_stage() -> None:
    assert platform_diagnostics.read_platform_metadata() == {
        "name": "SHEKU",
        "version": "1.6.0",
        "release_stage": "pre-production",
    }


@pytest.mark.parametrize(
    "source",
    [
        'PRODUCT_NAME = "SHEKU"\nPRODUCT_VERSION = "1.6.0"\nRELEASE_STAGE = "pre-production"\n',
        'PRODUCT_NAME: str = "SHEKU"\nPRODUCT_VERSION: str = "1.6.0"\n'
        'RELEASE_STAGE: ReleaseStage = "pre-production"\n',
    ],
)
def test_read_platform_metadata_accepts_untyped_and_typed_constants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
) -> None:
    metadata_file = tmp_path / platform_diagnostics.METADATA_FILE
    metadata_file.parent.mkdir(parents=True)
    metadata_file.write_text(source)
    monkeypatch.setattr(platform_diagnostics, "api_root", lambda: tmp_path)

    assert platform_diagnostics.read_platform_metadata() == {
        "name": "SHEKU",
        "version": "1.6.0",
        "release_stage": "pre-production",
    }


def test_read_platform_metadata_missing_values_preserve_unknown_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(platform_diagnostics, "api_root", lambda: tmp_path)

    assert platform_diagnostics.read_platform_metadata() == {
        "name": "Industrial AI Platform",
        "version": "unknown",
        "release_stage": "unknown",
    }


def test_release_candidate_projections_preserve_platform_metadata() -> None:
    platform = platform_diagnostics.read_platform_metadata()
    revision = "20260923_2830"
    evidence = {
        "plan": "release_candidate_evidence",
        "diagnostics": {
            "summary": {
                "migrations": {"current_revision": revision, "repository_head": revision},
                "runtime_profiles": {
                    "core": {"ready": True},
                    "document_management": {"ready": True},
                    "ai_services": {"ready": True},
                },
            }
        },
        "diagnostics_ready": True,
        "diagnostics_overall_status": "ready",
        "diagnostics_issue_count": 0,
        "diagnostics_critical_issue_count": 0,
        "closeout_status": "ready",
        "completion_status": "complete",
        "release_readiness_status": "ready",
        "evidence_consistency_status": "consistent",
        "safe_to_run_without_ai": True,
        "degraded_capabilities": [],
    }
    readiness = {
        "plan": "release_candidate_readiness",
        "platform": platform,
        "release_candidate_status": "eligible",
        "evidence": evidence,
        "command_catalog": {"plan": "commands", "commands": []},
        "gates": {"plan": "gates", "gates": []},
        "checklist": {"plan": "checklist"},
    }
    ci_contract = {
        "plan": "release_candidate_ci_contract",
        "release_candidate_status": "eligible",
        "blocking_checks": [],
        "optional_checks": [],
        "required_checks": [],
        "manual_execution_required": True,
    }

    manifest = platform_release_candidate.build_release_candidate_manifest_from_readiness(
        readiness, ci_contract
    )
    metadata = platform_release_candidate.build_release_metadata_from_manifest(manifest)
    summary = platform_release_candidate.build_release_summary_from_manifest(
        manifest,
        {"plan": "compatibility", "compatible_for_release_candidate": True},
        {"plan": "artifacts", "artifact_count": 0, "required_artifact_count": 0},
    )

    for projection in (manifest, metadata, summary):
        assert projection["platform"] == platform
        assert projection["release_stage"] == "pre-production"
        assert projection["current_version"] == "1.6.0"
        assert projection["migration_revision"] == revision
        assert projection["repository_head"] == revision
