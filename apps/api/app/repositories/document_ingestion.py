import json

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.documents import Chunk, DocumentVersion
from app.services.document_content_persistence import DocumentContentPersistenceResult
from app.services.ingestion_contracts import IngestionContractError
from app.services.lexical_indexing import LexicalIndexResult


class SqlAlchemyDocumentIngestionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_document_version_content(self, batch):
        self._validate_owner(batch.organization_id, batch.document_id, batch.document_version_id)
        existing = {
            row.chunk_index: row
            for row in self._session.scalars(
                select(Chunk).where(
                    Chunk.organization_id == batch.organization_id,
                    Chunk.document_record_id == batch.document_id,
                    Chunk.document_version_id == batch.document_version_id,
                )
            )
        }
        inserted = replaced = unchanged = 0
        retained = set()

        for unit in batch.units:
            retained.add(unit.ordinal)
            values = _values(batch, unit)
            row = existing.get(unit.ordinal)
            if row is None:
                self._session.add(Chunk(**values))
                inserted += 1
            elif _matches(row, values):
                unchanged += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.fts_vector = None
                replaced += 1

        stale = set(existing) - retained
        if stale:
            self._session.execute(
                delete(Chunk).where(
                    Chunk.organization_id == batch.organization_id,
                    Chunk.document_record_id == batch.document_id,
                    Chunk.document_version_id == batch.document_version_id,
                    Chunk.chunk_index.in_(stale),
                )
            )

        self._session.flush()
        return DocumentContentPersistenceResult(
            inserted_units=inserted,
            replaced_units=replaced,
            unchanged_units=unchanged,
            idempotency_key=batch.idempotency_key,
        )

    def replace_document_version_index(self, batch):
        self._validate_owner(batch.organization_id, batch.document_id, batch.document_version_id)
        rows = {
            row.chunk_key: row
            for row in self._session.scalars(
                select(Chunk).where(
                    Chunk.organization_id == batch.organization_id,
                    Chunk.document_record_id == batch.document_id,
                    Chunk.document_version_id == batch.document_version_id,
                )
            )
        }
        if len(rows) != len(batch.documents):
            raise IngestionContractError("persisted chunk count does not match lexical batch")

        for document in batch.documents:
            row = rows.get(document.unit_key)
            if row is None or row.content_hash != document.content_hash:
                raise IngestionContractError("persisted chunk does not match lexical document")
            row.fts_vector = func.to_tsvector(document.language_config, document.search_text)
            row.status = "indexed"

        self._session.flush()
        return LexicalIndexResult(
            indexed_documents=len(batch.documents),
            unchanged_documents=0,
            idempotency_key=batch.idempotency_key,
        )

    def _validate_owner(self, organization_id, document_id, document_version_id) -> None:
        version = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == document_version_id,
                DocumentVersion.organization_id == organization_id,
                DocumentVersion.document_record_id == document_id,
            )
        )
        if version is None:
            raise IngestionContractError("document version ownership validation failed")


def _values(batch, unit):
    return {
        "organization_id": batch.organization_id,
        "document_record_id": batch.document_id,
        "document_version_id": batch.document_version_id,
        "chunk_index": unit.ordinal,
        "chunk_key": unit.unit_key,
        "content_hash": unit.content_hash,
        "semantic_hash": None,
        "text": _text(unit),
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


def _text(unit):
    if unit.text is not None:
        return unit.text
    if unit.structured_data is not None:
        return json.dumps(unit.structured_data, ensure_ascii=False, sort_keys=True, default=str)
    raise IngestionContractError("content unit has no persistable representation")


def _matches(row, values):
    scalar_keys = (
        "chunk_key",
        "content_hash",
        "text",
        "content_type",
        "section_ref",
        "quality",
        "metadata_json",
    )
    if not all(getattr(row, key) == values[key] for key in scalar_keys):
        return False

    current_provenance = dict(row.provenance or {})
    expected_provenance = dict(values["provenance"])
    current_provenance.pop("execution_id", None)
    expected_provenance.pop("execution_id", None)
    return current_provenance == expected_provenance
