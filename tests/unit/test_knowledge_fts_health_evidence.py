from __future__ import annotations

from app.repositories.knowledge_fts import _health_from_catalog_evidence


def test_fts_health_requires_generated_tsvector_and_valid_gin_index() -> None:
    health = _health_from_catalog_evidence(
        column={
            "data_type": "tsvector",
            "generated_kind": "s",
            "generation_expression": "to_tsvector('simple'::regconfig, COALESCE(text, ''::text))",
        },
        index={
            "is_valid": True,
            "is_ready": True,
            "access_method": "gin",
            "index_definition": "CREATE INDEX USING gin",
        },
        indexed_chunks=7,
    )

    assert health["fts_projection_ready"] is True
    assert health["fts_index_created"] is True
    assert health["fts_index_valid"] is True
    assert health["fts_backfill_completed"] is True
    assert health["fts_backfill_mode"] == "generated_column"
    assert health["search_uses_postgresql_fts"] is True
    assert health["indexed_chunks"] == 7


def test_fts_health_fails_closed_without_physical_index_evidence() -> None:
    health = _health_from_catalog_evidence(
        column={
            "data_type": "tsvector",
            "generated_kind": "s",
            "generation_expression": "to_tsvector('simple'::regconfig, COALESCE(text, ''::text))",
        },
        index=None,
        indexed_chunks=3,
    )

    assert health["fts_projection_ready"] is True
    assert health["fts_index_created"] is False
    assert health["fts_index_valid"] is False
    assert health["search_uses_postgresql_fts"] is False


def test_fts_health_fails_closed_for_non_generated_projection() -> None:
    health = _health_from_catalog_evidence(
        column={
            "data_type": "tsvector",
            "generated_kind": "",
            "generation_expression": None,
        },
        index={
            "is_valid": True,
            "is_ready": True,
            "access_method": "gin",
            "index_definition": "CREATE INDEX USING gin",
        },
        indexed_chunks=1,
    )

    assert health["fts_projection_ready"] is False
    assert health["fts_backfill_completed"] is False
    assert health["search_uses_postgresql_fts"] is False
