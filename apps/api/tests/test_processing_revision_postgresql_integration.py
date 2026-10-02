import os

import pytest
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is not configured")


def test_processing_revision_schema_in_postgresql():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        chunk_column = connection.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema='documents' AND table_name='chunks' "
                "AND column_name='processing_revision_id'"
            )
        ).scalar_one()
        fts_type = connection.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema='documents' AND table_name='chunks' "
                "AND column_name='fts_vector'"
            )
        ).scalar_one()
        fk_target = connection.execute(
            text(
                "SELECT ccu.table_schema || '.' || ccu.table_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.constraint_column_usage ccu "
                "ON ccu.constraint_name=tc.constraint_name "
                "AND ccu.constraint_schema=tc.constraint_schema "
                "WHERE tc.constraint_schema='documents' AND tc.table_name='chunks' "
                "AND tc.constraint_name='fk_chunks_processing_revision_id' "
                "AND tc.constraint_type='FOREIGN KEY'"
            )
        ).scalar_one()
        partial_index = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname='documents' AND tablename='chunks' "
                "AND indexname='uq_chunks_revision_chunk_key'"
            )
        ).scalar_one()
        processing_index = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='documents' AND tablename='chunks' "
                "AND indexname='ix_chunks_processing_revision_id'"
            )
        ).scalar_one()

    engine.dispose()
    assert version >= "20260619_2160"
    assert chunk_column == "uuid"
    assert fts_type == "tsvector"
    assert fk_target == "documents.processing_revisions"
    assert "UNIQUE INDEX" in partial_index
    assert "processing_revision_id IS NOT NULL" in partial_index
    assert processing_index == "ix_chunks_processing_revision_id"
