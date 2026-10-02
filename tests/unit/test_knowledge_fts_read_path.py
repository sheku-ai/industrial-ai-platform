from __future__ import annotations

from typing import Any

import app.services.knowledge_fts_runtime as runtime


class _ReadOnlyRepository:
    def __init__(self, _db: Any) -> None:
        self.backfill_called = False

    def backfill_fts_projection(self) -> dict[str, Any]:
        self.backfill_called = True
        raise AssertionError("FTS search must not backfill the projection")

    def fts_health(self) -> dict[str, Any]:
        return {
            "fts_index_created": True,
            "fts_backfill_completed": True,
            "fts_config": "simple",
            "indexed_chunks": 1,
            "search_vector_column": "knowledge.chunks.search_vector",
            "gin_index": "ix_knowledge_chunks_search_vector",
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
        }

    def indexed_chunk_count(self, *, organization_id: str | None = None) -> int:
        return 1

    def search_fts(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "records": [],
            "total_count": 0,
            "offset": 0,
            "limit": 5,
            "has_more": False,
            "facets": {},
        }


def test_fts_search_uses_existing_projection_without_backfill(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "KnowledgeIndexRepository", _ReadOnlyRepository)

    payload = runtime.build_knowledge_fts_search(
        object(),
        query="inspection",
        top_k=5,
        persist_snapshot=False,
    )

    assert payload["fts_search_status"] == runtime.FTS_SEARCH_STATUS_COMPLETED
    assert payload["fts_search_succeeded"] is True
    assert payload["fts_projection"]["fts_index_created"] is True
    assert payload["fts_projection"]["search_uses_postgresql_fts"] is True
