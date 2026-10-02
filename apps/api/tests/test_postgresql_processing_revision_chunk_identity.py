from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="explicit PostgreSQL integration environment is required",
)


def test_processing_revision_and_chunk_identity_schema_contract():
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)

    try:
        inspector = inspect(engine)
        revision_columns = {
            column["name"]: str(column["type"])
            for column in inspector.get_columns("processing_revisions", schema="documents")
        }
        chunk_columns = {
            column["name"]: str(column["type"])
            for column in inspector.get_columns("chunks", schema="documents")
        }
        revision_indexes = inspector.get_indexes("processing_revisions", schema="documents")
        chunk_indexes = inspector.get_indexes("chunks", schema="documents")

        assert {
            "id",
            "organization_id",
            "document_record_id",
            "document_version_id",
            "runtime_execution_id",
            "runtime_attempt_id",
            "adapter_key",
            "adapter_version",
            "configuration_snapshot",
            "source_checksum_sha256",
            "status",
            "started_at",
            "completed_at",
            "chunk_count",
        }.issubset(revision_columns)
        assert "processing_revision_id" in chunk_columns
        assert "chunk_key" in chunk_columns
        assert "content_hash" in chunk_columns

        assert any(
            index.get("unique")
            and "runtime_attempt_id" in index.get("column_names", [])
            for index in revision_indexes
        )
        assert any(
            index.get("unique")
            and "processing_revision_id" in index.get("column_names", [])
            and "chunk_key" in index.get("column_names", [])
            for index in chunk_indexes
        )
    finally:
        engine.dispose()
