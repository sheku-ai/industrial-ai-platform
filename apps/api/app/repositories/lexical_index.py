from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.documents import Chunk
from app.services.lexical_indexing import LexicalIndexBatch, LexicalIndexResult


class PostgreSqlLexicalIndexRepository:
    """Maintain PostgreSQL FTS state on the current chunk materialization."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_document_version_index(self, batch: LexicalIndexBatch) -> LexicalIndexResult:
        chunks = list(
            self.session.scalars(
                select(Chunk)
                .where(
                    Chunk.organization_id == batch.organization_id,
                    Chunk.document_version_id == batch.document_version_id,
                )
                .order_by(Chunk.chunk_index.asc())
                .with_for_update()
            ).all()
        )
        by_index = {chunk.chunk_index: chunk for chunk in chunks}
        indexed = 0
        unchanged = 0

        for document in batch.documents:
            chunk = by_index.get(document.ordinal)
            if chunk is None:
                raise ValueError("lexical document has no persisted chunk")
            expected = func.to_tsvector(document.language_config, document.search_text)
            self.session.execute(
                update(Chunk)
                .where(
                    Chunk.id == chunk.id,
                    Chunk.organization_id == batch.organization_id,
                )
                .values(fts_vector=expected)
            )
            indexed += 1

        self.session.flush()
        return LexicalIndexResult(
            indexed_documents=indexed,
            unchanged_documents=unchanged,
            idempotency_key=batch.idempotency_key,
        )
