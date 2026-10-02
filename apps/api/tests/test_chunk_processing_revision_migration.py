from pathlib import Path


def test_chunk_processing_revision_migration_is_additive():
    migration = Path("alembic/versions/20260619_2160_chunk_processing_revision.py").read_text(encoding="utf-8")

    assert 'revision: str = "20260619_2160"' in migration
    assert 'down_revision: str | None = "20260619_2150"' in migration
    assert 'sa.Column("processing_revision_id"' in migration
    assert 'nullable=True' in migration
    assert 'fk_chunks_processing_revision_id' in migration
    assert 'uq_chunks_revision_chunk_key' in migration
    assert 'processing_revision_id IS NOT NULL' in migration
    assert 'uq_chunks_version_index' not in migration


def test_chunk_revision_identity_uses_platform_scope():
    migration = Path("alembic/versions/20260619_2160_chunk_processing_revision.py").read_text(encoding="utf-8")

    assert '["organization_id", "processing_revision_id", "chunk_key"]' in migration
    assert 'ondelete="RESTRICT"' in migration
