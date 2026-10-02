from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.repositories.knowledge_index import KnowledgeIndexRepository as BaseKnowledgeIndexRepository

SEARCH_VECTOR_COLUMN = "knowledge.chunks.search_vector"
SEARCH_VECTOR_INDEX = "ix_knowledge_chunks_search_vector"


def _health_from_catalog_evidence(
    *,
    column: dict[str, Any] | None,
    index: dict[str, Any] | None,
    indexed_chunks: int,
) -> dict[str, Any]:
    column = dict(column or {})
    index = dict(index or {})
    generation_expression = str(column.get("generation_expression") or "")
    column_exists = bool(column)
    column_is_tsvector = str(column.get("data_type") or "") == "tsvector"
    column_is_generated = str(column.get("generated_kind") or "") == "s"
    fts_config_verified = "to_tsvector" in generation_expression and "'simple'::regconfig" in generation_expression
    projection_ready = column_exists and column_is_tsvector and column_is_generated and fts_config_verified

    index_exists = bool(index)
    index_is_gin = str(index.get("access_method") or "") == "gin"
    index_valid = bool(index.get("is_valid")) and bool(index.get("is_ready")) and index_is_gin
    fts_ready = projection_ready and index_exists and index_valid

    return {
        "fts_index_created": index_exists,
        "fts_index_valid": index_valid,
        "fts_backfill_completed": projection_ready,
        "fts_backfill_mode": "generated_column",
        "fts_projection_ready": projection_ready,
        "fts_config": "simple",
        "fts_config_verified": fts_config_verified,
        "indexed_chunks": int(indexed_chunks),
        "search_vector_column": SEARCH_VECTOR_COLUMN,
        "search_vector_column_exists": column_exists,
        "search_vector_data_type": column.get("data_type"),
        "search_vector_generated": column_is_generated,
        "search_vector_generation_expression": generation_expression or None,
        "gin_index": SEARCH_VECTOR_INDEX,
        "gin_index_exists": index_exists,
        "gin_index_valid": index_valid,
        "gin_index_access_method": index.get("access_method"),
        "gin_index_definition": index.get("index_definition"),
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": fts_ready,
    }


class KnowledgeIndexRepository(BaseKnowledgeIndexRepository):
    def fts_health(self) -> dict[str, Any]:
        column_row = self.session.execute(
            text(
                """
                SELECT
                    format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
                    attribute.attgenerated AS generated_kind,
                    pg_get_expr(attribute_default.adbin, attribute_default.adrelid) AS generation_expression
                FROM pg_attribute AS attribute
                JOIN pg_class AS table_class ON table_class.oid = attribute.attrelid
                JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace
                LEFT JOIN pg_attrdef AS attribute_default
                    ON attribute_default.adrelid = attribute.attrelid
                    AND attribute_default.adnum = attribute.attnum
                WHERE namespace.nspname = 'knowledge'
                    AND table_class.relname = 'chunks'
                    AND attribute.attname = 'search_vector'
                    AND NOT attribute.attisdropped
                LIMIT 1
                """
            )
        ).mappings().one_or_none()
        index_row = self.session.execute(
            text(
                """
                SELECT
                    index_state.indisvalid AS is_valid,
                    index_state.indisready AS is_ready,
                    access_method.amname AS access_method,
                    pg_get_indexdef(index_class.oid) AS index_definition
                FROM pg_index AS index_state
                JOIN pg_class AS table_class ON table_class.oid = index_state.indrelid
                JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace
                JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                JOIN pg_am AS access_method ON access_method.oid = index_class.relam
                WHERE namespace.nspname = 'knowledge'
                    AND table_class.relname = 'chunks'
                    AND index_class.relname = 'ix_knowledge_chunks_search_vector'
                LIMIT 1
                """
            )
        ).mappings().one_or_none()
        return _health_from_catalog_evidence(
            column=dict(column_row) if column_row is not None else None,
            index=dict(index_row) if index_row is not None else None,
            indexed_chunks=self.indexed_chunk_count(),
        )
