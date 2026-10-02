import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_manifests_match_current_runtime_release() -> None:
    manifest = json.loads((ROOT / "release/manifest.json").read_text())
    community = json.loads((ROOT / "release/editions/community.json").read_text())
    enterprise = json.loads((ROOT / "release/editions/enterprise.json").read_text())

    assert manifest["version"] == "1.6.0"
    assert manifest["alembic_head"] == "20260930_2870"
    assert manifest["supported_editions"] == ["community", "enterprise"]
    assert manifest["supported_postgresql_version"] == "16"
    assert manifest["upgrade_from"] == ["1.5.2"]
    assert manifest["rollback_target"] == "1.5.2"
    assert manifest["database_rollback_policy"] == "restore_required_when_migration_is_not_reversible"

    for edition_manifest, edition in ((community, "community"), (enterprise, "enterprise")):
        assert edition_manifest["edition"] == edition
        assert edition_manifest["version"] == manifest["version"]
        assert edition_manifest["alembic_head"] == manifest["alembic_head"]
