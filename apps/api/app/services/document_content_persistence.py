from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.services.ingestion_contracts import ContentUnit, ExtractionResult, IngestionContractError


@dataclass(frozen=True)
class DocumentContentWriteBatch:
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    execution_id: UUID
    adapter_key: str
    adapter_version: str
    pipeline_profile_revision: str
    units: tuple[ContentUnit, ...]
    processing_revision_id: UUID | None = None
    replace_existing: bool = True

    def __post_init__(self) -> None:
        if not self.adapter_key.strip():
            raise IngestionContractError("adapter_key is required")
        if not self.adapter_version.strip():
            raise IngestionContractError("adapter_version is required")
        if not self.pipeline_profile_revision.strip():
            raise IngestionContractError("pipeline_profile_revision is required")
        if not self.units:
            raise IngestionContractError("content persistence requires at least one unit")
        ordinals = [unit.ordinal for unit in self.units]
        if any(value < 0 for value in ordinals) or len(ordinals) != len(set(ordinals)):
            raise IngestionContractError("content unit ordinals must be unique and non-negative")

    @property
    def idempotency_key(self) -> str:
        base = (
            f"{self.organization_id}:{self.document_version_id}:{self.adapter_key}:"
            f"{self.adapter_version}:{self.pipeline_profile_revision}"
        )
        return f"{base}:{self.processing_revision_id}" if self.processing_revision_id else base


@dataclass(frozen=True)
class DocumentContentPersistenceResult:
    inserted_units: int
    replaced_units: int
    unchanged_units: int
    idempotency_key: str

    def __post_init__(self) -> None:
        for name, value in (
            ("inserted_units", self.inserted_units),
            ("replaced_units", self.replaced_units),
            ("unchanged_units", self.unchanged_units),
        ):
            if value < 0:
                raise IngestionContractError(f"{name} cannot be negative")
        if not self.idempotency_key.strip():
            raise IngestionContractError("idempotency_key is required")


class DocumentContentRepository(Protocol):
    def replace_document_version_content(
        self, batch: DocumentContentWriteBatch
    ) -> DocumentContentPersistenceResult: ...


class DocumentContentPersistenceService:
    def __init__(self, repository: DocumentContentRepository) -> None:
        self._repository = repository

    def persist_extraction(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        execution_id: UUID,
        pipeline_profile_revision: str,
        extraction: ExtractionResult,
        processing_revision_id: UUID | None = None,
    ) -> DocumentContentPersistenceResult:
        batch = DocumentContentWriteBatch(
            organization_id=organization_id,
            document_id=document_id,
            document_version_id=document_version_id,
            execution_id=execution_id,
            adapter_key=extraction.adapter_key,
            adapter_version=extraction.adapter_version,
            pipeline_profile_revision=pipeline_profile_revision,
            units=extraction.content_units,
            processing_revision_id=processing_revision_id,
            replace_existing=not bool(extraction.metrics.get("partial_segment_update", False)),
        )
        result = self._repository.replace_document_version_content(batch)
        if result.idempotency_key != batch.idempotency_key:
            raise IngestionContractError("repository returned an unexpected idempotency key")
        total = result.inserted_units + result.replaced_units + result.unchanged_units
        if total != len(batch.units):
            raise IngestionContractError("repository persistence counts do not match content units")
        return result
