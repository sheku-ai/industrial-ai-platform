from pathlib import Path


def test_artifact_publication_migration_contract():
    migration = Path("alembic/versions/20260619_2180_artifact_publications.py").read_text(encoding="utf-8")

    assert 'revision = "20260619_2180"' in migration
    assert 'down_revision = "20260619_2160"' in migration
    assert '"artifact_publications"' in migration
    assert '"fk_runtime_artifact_publications_artifact"' in migration
    assert '"fk_runtime_artifact_publications_attempt"' in migration
    assert '"uq_runtime_artifact_publications_number"' in migration
    assert '"ix_runtime_artifact_publications_status"' in migration
    assert '"ix_runtime_artifact_publications_artifact"' in migration
    assert "checksum_conflict" in migration
    assert "reconciliation_required" in migration
    assert 'ondelete="CASCADE"' in migration
