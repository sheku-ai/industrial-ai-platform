from pathlib import Path


def test_processing_revision_migration_is_additive():
    migration = Path("alembic/versions/20260619_2140_processing_revisions.py").read_text(encoding="utf-8")

    assert 'revision: str = "20260619_2140"' in migration
    assert 'down_revision: str | None = "20260619_2130"' in migration
    assert 'Revises: 20260619_2130' in migration
    assert '"processing_revisions"' in migration
    assert "uq_processing_revisions_runtime_attempt" in migration
    assert "runtime_execution_id" in migration
    assert "runtime_attempt_id" in migration
    assert "documents.ingestion_pipeline_profiles.id" in migration
    assert "ingestion.pipeline_profiles.id" not in migration
