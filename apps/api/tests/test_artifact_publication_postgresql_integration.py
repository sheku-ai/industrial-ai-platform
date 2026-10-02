import os

import pytest
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is not configured")


def test_artifact_publication_schema_in_postgresql():
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            columns = {
                row.column_name: row.data_type
                for row in connection.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema='runtime' AND table_name='artifact_publications'"
                    )
                )
            }
            constraints = {
                row.constraint_name: row.constraint_type
                for row in connection.execute(
                    text(
                        "SELECT constraint_name, constraint_type "
                        "FROM information_schema.table_constraints "
                        "WHERE constraint_schema='runtime' AND table_name='artifact_publications'"
                    )
                )
            }
            check_definitions = [
                row.definition
                for row in connection.execute(
                    text("""
                    SELECT pg_get_constraintdef(c.oid) AS definition
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'runtime'
                      AND t.relname = 'artifact_publications'
                      AND c.contype = 'c'
                """)
                )
            ]
            indexes = {
                row.indexname: row.indexdef
                for row in connection.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname='runtime' AND tablename='artifact_publications'"
                    )
                )
            }

        assert version >= "20260619_2180"
        assert columns["id"] == "uuid"
        assert columns["organization_id"] == "uuid"
        assert columns["execution_id"] == "uuid"
        assert columns["artifact_id"] == "uuid"
        assert columns["attempt_id"] == "uuid"
        assert columns["publication_number"] == "integer"
        assert columns["storage_uri"] == "text"
        assert columns["metadata"] == "jsonb"

        assert constraints["fk_runtime_artifact_publications_artifact"] == "FOREIGN KEY"
        assert constraints["fk_runtime_artifact_publications_attempt"] == "FOREIGN KEY"
        assert constraints["uq_runtime_artifact_publications_number"] == "UNIQUE"

        assert any(
            "status" in definition and "checksum_conflict" in definition and "reconciliation_required" in definition
            for definition in check_definitions
        )
        assert any(
            "verified_at IS NULL" in definition and "published_at IS NOT NULL" in definition
            for definition in check_definitions
        )

        assert "ix_runtime_artifact_publications_status" in indexes
        assert "ix_runtime_artifact_publications_artifact" in indexes
        assert "artifact_id, publication_number" in indexes["uq_runtime_artifact_publications_number"]
    finally:
        engine.dispose()
