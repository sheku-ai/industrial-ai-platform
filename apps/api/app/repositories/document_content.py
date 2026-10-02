from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.documents import Chunk
from app.services.document_content_persistence import (
    DocumentContentPersistenceResult,
    DocumentContentWriteBatch,
)


class SqlAlchemyDocumentContentRepository:
    """Maintain the current materialized chunk set for one document version.

    Processing revisions preserve execution lineage. The chunks table remains the
    current query materialization, protected by the existing version/index
    uniqueness contract. The caller owns commit and rollback.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_document_version_content(
        self,
        batch: DocumentContentWriteBatch,
    ) -> DocumentContentPersistenceResult:
        existing = list(
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
        by_index = {chunk.chunk_index: chunk for chunk in existing}
        expected_indexes = {unit.ordinal for unit in batch.units}

        inserted = 0
        replaced = 0
        unchanged = 0

        for unit in batch.units:
            current = by_index.get(unit.ordinal)
            values = self._chunk_values(batch, unit)
            if current is None:
                self.session.add(Chunk(**values))
                inserted += 1
                continue

            if self._matches(current, values):
                unchanged += 1
                continue

            for name, value in values.items():
                setattr(current, name, value)
            replaced += 1

        stale_ids = [chunk.id for chunk in existing if chunk.chunk_index not in expected_indexes]
        if stale_ids:
            self.session.execute(
                delete(Chunk).where(
                    Chunk.organization_id == batch.organization_id,
                    Chunk.id.in_(stale_ids),
                )
            )

        self.session.flush()
        return DocumentContentPersistenceResult(
            inserted_units=inserted,
            replaced_units=replaced,
            unchanged_units=unchanged,
            idempotency_key=batch.idempotency_key,
        )

    @staticmethod
    def _chunk_values(batch, unit) -> dict:
        text_value = unit.text
        if text_value is None:
            text_value = json.dumps(
                unit.structured_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return {
            "organization_id": batch.organization_id,
            "document_record_id": batch.document_id,
            "document_version_id": batch.document_version_id,
            "processing_revision_id": batch.processing_revision_id,
            "artifact_id": None,
            "collection_id": None,
            "chunk_index": unit.ordinal,
            "chunk_key": unit.unit_key,
            "content_hash": unit.content_hash,
            "semantic_hash": None,
            "text": text_value,
            "content_type": unit.unit_type.value,
            "section_ref": dict(unit.source_locator),
            "provenance": {
                "execution_id": str(batch.execution_id),
                "adapter_key": batch.adapter_key,
                "adapter_version": batch.adapter_version,
                "pipeline_profile_revision": batch.pipeline_profile_revision,
            },
            "quality": {},
            "metadata_json": dict(unit.attributes),
            "status": "created",
        }

    @staticmethod
    def _matches(chunk: Chunk, values: dict) -> bool:
        comparable_fields = (
            "document_record_id",
            "document_version_id",
            "processing_revision_id",
            "chunk_index",
            "chunk_key",
            "content_hash",
            "text",
            "content_type",
            "section_ref",
            "provenance",
            "quality",
            "metadata_json",
            "status",
        )
        return all(getattr(chunk, field) == values[field] for field in comparable_fields)
