from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.services.ingestion_contracts import ContentUnit, IngestionContractError


@dataclass(frozen=True)
class LexicalIndexDocument:
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    unit_key: str
    ordinal: int
    content_hash: str
    search_text: str
    language_config: str
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.unit_key.strip():
            raise IngestionContractError("unit_key is required")
        if self.ordinal < 0:
            raise IngestionContractError("ordinal must be non-negative")
        if len(self.content_hash) != 64:
            raise IngestionContractError("content_hash must be SHA-256")
        if not self.search_text.strip():
            raise IngestionContractError("search_text is required")
        if not self.language_config.strip():
            raise IngestionContractError("language_config is required")
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True)
class LexicalIndexBatch:
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    execution_id: UUID
    pipeline_profile_revision: str
    documents: tuple[LexicalIndexDocument, ...]

    def __post_init__(self) -> None:
        if not self.pipeline_profile_revision.strip():
            raise IngestionContractError("pipeline_profile_revision is required")
        if not self.documents:
            raise IngestionContractError("lexical indexing requires at least one document")
        for document in self.documents:
            if document.organization_id != self.organization_id:
                raise IngestionContractError("lexical document organization mismatch")
            if document.document_id != self.document_id:
                raise IngestionContractError("lexical document id mismatch")
            if document.document_version_id != self.document_version_id:
                raise IngestionContractError("lexical document version mismatch")

    @property
    def idempotency_key(self) -> str:
        return f"{self.organization_id}:{self.document_version_id}:{self.pipeline_profile_revision}:lexical"


@dataclass(frozen=True)
class LexicalIndexResult:
    indexed_documents: int
    unchanged_documents: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.indexed_documents < 0 or self.unchanged_documents < 0:
            raise IngestionContractError("lexical index counts cannot be negative")
        if not self.idempotency_key.strip():
            raise IngestionContractError("idempotency_key is required")


class LexicalIndexRepository(Protocol):
    def replace_document_version_index(
        self,
        batch: LexicalIndexBatch,
    ) -> LexicalIndexResult: ...


class LexicalIndexService:
    """Build and publish PostgreSQL FTS-ready lexical documents."""

    def __init__(self, repository: LexicalIndexRepository) -> None:
        self._repository = repository

    def index_units(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        execution_id: UUID,
        pipeline_profile_revision: str,
        units: tuple[ContentUnit, ...],
        language_config: str = "simple",
    ) -> LexicalIndexResult:
        documents = tuple(
            self._to_lexical_document(
                organization_id,
                document_id,
                document_version_id,
                unit,
                language_config,
            )
            for unit in units
        )
        batch = LexicalIndexBatch(
            organization_id=organization_id,
            document_id=document_id,
            document_version_id=document_version_id,
            execution_id=execution_id,
            pipeline_profile_revision=pipeline_profile_revision,
            documents=documents,
        )
        result = self._repository.replace_document_version_index(batch)
        if result.idempotency_key != batch.idempotency_key:
            raise IngestionContractError("repository returned unexpected lexical idempotency key")
        if result.indexed_documents + result.unchanged_documents != len(documents):
            raise IngestionContractError("lexical repository counts do not match documents")
        return result

    @staticmethod
    def _to_lexical_document(
        organization_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        unit: ContentUnit,
        language_config: str,
    ) -> LexicalIndexDocument:
        if unit.text is not None:
            search_text = unit.text
        elif unit.structured_data is not None:
            search_text = " ".join(
                str(value) for key, value in sorted(unit.structured_data.items()) if value is not None
            )
        else:
            raise IngestionContractError("content unit has no lexical representation")

        if not search_text.strip():
            raise IngestionContractError("content unit produced empty lexical text")

        return LexicalIndexDocument(
            organization_id=organization_id,
            document_id=document_id,
            document_version_id=document_version_id,
            unit_key=unit.unit_key,
            ordinal=unit.ordinal,
            content_hash=unit.content_hash,
            search_text=search_text,
            language_config=language_config,
            attributes=unit.attributes,
        )
