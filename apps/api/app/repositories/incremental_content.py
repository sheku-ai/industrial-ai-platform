from sqlalchemy import select

from app.models.documents import Chunk
from app.repositories.document_content import SqlAlchemyDocumentContentRepository
from app.services.document_content_persistence import DocumentContentPersistenceResult


class IncrementalContentRepository(SqlAlchemyDocumentContentRepository):
    def replace_document_version_content(self, batch):
        if batch.replace_existing:
            return super().replace_document_version_content(batch)
        rows = self.session.scalars(
            select(Chunk)
            .where(
                Chunk.organization_id == batch.organization_id,
                Chunk.document_version_id == batch.document_version_id,
            )
            .with_for_update()
        ).all()
        current = {row.chunk_index: row for row in rows}
        inserted = replaced = unchanged = 0
        for unit in batch.units:
            values = self._chunk_values(batch, unit)
            row = current.get(unit.ordinal)
            if row is None:
                self.session.add(Chunk(**values))
                inserted += 1
            elif self._matches(row, values):
                unchanged += 1
            else:
                for name, value in values.items():
                    setattr(row, name, value)
                replaced += 1
        self.session.flush()
        return DocumentContentPersistenceResult(inserted, replaced, unchanged, batch.idempotency_key)
