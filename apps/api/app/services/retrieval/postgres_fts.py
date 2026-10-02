"""PostgreSQL Full Text Search retrieval provider.

This module implements the Sprint 10.1 lexical retrieval boundary.

Design constraints:
- PostgreSQL remains the system of record.
- FTS is a productized retrieval provider, not a smoke path.
- Filters remain generic and configuration-compatible.
- No customer, plant, site, asset, department, role, country, workflow,
  taxonomy, or vector collection assumption is encoded here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, literal_column, or_
from sqlalchemy.orm import Session

from app.models.documents import Chunk
from app.services.retrieval.contracts import RetrievalCandidate, RetrievalQuery, RetrievalSource
from app.services.retrieval.interfaces import LexicalRetriever, VectorRetriever
from app.services.retrieval.processing_revision_selection import (
    ProcessingRevisionSelection,
    apply_processing_revision_selection,
    candidate_revision_metadata,
    parse_processing_revision_selection,
)

FTS_CONFIG = literal_column("'simple'")


class PostgresFtsRetriever(LexicalRetriever):
    """Retrieves persisted chunks using PostgreSQL Full Text Search."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievalCandidate, ...]:
        ts_query = func.websearch_to_tsquery(FTS_CONFIG, query.query_text)
        text_vector = func.to_tsvector(FTS_CONFIG, func.coalesce(Chunk.text, ""))
        searchable_vector = func.coalesce(Chunk.fts_vector, text_vector)
        rank = func.ts_rank_cd(searchable_vector, ts_query).label("fts_rank")

        selection, metadata_filters = parse_processing_revision_selection(query.filters.metadata)
        db_query = (
            self.db.query(Chunk, rank)
            .filter(Chunk.organization_id == query.filters.organization_id)
            .filter(searchable_vector.op("@@")(ts_query))
        )

        if query.filters.collection_ids:
            db_query = db_query.filter(Chunk.collection_id.in_(query.filters.collection_ids))

        if query.filters.document_record_ids:
            db_query = db_query.filter(Chunk.document_record_id.in_(query.filters.document_record_ids))

        if query.filters.document_version_ids:
            db_query = db_query.filter(Chunk.document_version_id.in_(query.filters.document_version_ids))

        db_query = apply_processing_revision_selection(
            db_query,
            selection,
            organization_id=query.filters.organization_id,
        )
        db_query = _apply_metadata_filters(db_query, metadata_filters)

        rows = db_query.order_by(desc(rank), desc(Chunk.created_at)).limit(query.candidate_k).all()

        return tuple(
            self._to_candidate(chunk=chunk, score=float(score or 0.0), selection=selection) for chunk, score in rows
        )

    @staticmethod
    def _to_candidate(
        chunk: Chunk,
        score: float,
        selection: ProcessingRevisionSelection,
    ) -> RetrievalCandidate:
        metadata: dict[str, Any] = dict(chunk.metadata_json or {})
        metadata.setdefault("content_type", chunk.content_type)
        metadata.setdefault("section_ref", chunk.section_ref or {})
        metadata.setdefault("provenance", chunk.provenance or {})
        metadata.setdefault("quality", chunk.quality or {})
        metadata.setdefault("retrieval_provider", "postgres_fts")
        metadata.setdefault("content_modality", "text")
        metadata.setdefault("evidence_role", "authoritative")
        metadata.setdefault("authoritative", metadata["evidence_role"] == "authoritative")
        metadata.setdefault("derived_content", metadata["evidence_role"] == "derived")
        metadata.setdefault(
            "citation_basis",
            "derived_visual_description" if metadata["content_modality"] == "visual_description" else "source_text",
        )
        metadata.update(candidate_revision_metadata(chunk, selection))
        if "source_locator" not in metadata:
            metadata["source_locator"] = dict(metadata.get("provenance") or metadata.get("section_ref") or {})

        return RetrievalCandidate(
            chunk_id=chunk.id,
            organization_id=chunk.organization_id,
            document_record_id=chunk.document_record_id,
            document_version_id=chunk.document_version_id,
            collection_id=chunk.collection_id,
            chunk_key=chunk.chunk_key,
            text=chunk.text,
            source=RetrievalSource.LEXICAL,
            score=score,
            content_hash=chunk.content_hash,
            metadata=metadata,
            classification={},
        )


def _apply_metadata_filters(db_query, filters: dict[str, Any]):
    if not filters:
        return db_query
    remaining = dict(filters)
    modality = remaining.pop("content_modality", None)
    role = remaining.pop("evidence_role", None)

    if modality == "text":
        db_query = db_query.filter(
            or_(
                Chunk.metadata_json["content_modality"].astext == "text",
                Chunk.metadata_json["content_modality"].astext.is_(None),
            )
        )
    elif modality is not None:
        db_query = db_query.filter(Chunk.metadata_json["content_modality"].astext == str(modality))

    if role == "authoritative":
        db_query = db_query.filter(
            or_(
                Chunk.metadata_json["evidence_role"].astext == "authoritative",
                Chunk.metadata_json["evidence_role"].astext.is_(None),
            )
        )
    elif role is not None:
        db_query = db_query.filter(Chunk.metadata_json["evidence_role"].astext == str(role))

    if remaining:
        db_query = db_query.filter(Chunk.metadata_json.contains(remaining))
    return db_query


class DisabledVectorRetriever(VectorRetriever):
    """Vector retriever placeholder used while vector providers remain optional."""

    def retrieve(self, query: RetrievalQuery) -> tuple[RetrievalCandidate, ...]:
        return ()
