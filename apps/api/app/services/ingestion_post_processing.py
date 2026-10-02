from dataclasses import dataclass
from uuid import UUID

from app.services.document_content_persistence import (
    DocumentContentPersistenceResult,
    DocumentContentPersistenceService,
)
from app.services.ingestion_contracts import ExtractionResult, IngestionContractError
from app.services.lexical_indexing import LexicalIndexResult, LexicalIndexService


@dataclass(frozen=True)
class IngestionPostProcessingResult:
    persistence: DocumentContentPersistenceResult
    lexical_index: LexicalIndexResult


class IngestionPostProcessingService:
    def __init__(self, persistence: DocumentContentPersistenceService, lexical_index: LexicalIndexService) -> None:
        self._persistence = persistence
        self._lexical_index = lexical_index

    def process(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        execution_id: UUID,
        pipeline_profile_revision: str,
        extraction: ExtractionResult,
        language_config: str = "simple",
        processing_revision_id: UUID | None = None,
    ) -> IngestionPostProcessingResult:
        if not pipeline_profile_revision.strip():
            raise IngestionContractError("pipeline_profile_revision is required")
        persisted = self._persistence.persist_extraction(
            organization_id=organization_id,
            document_id=document_id,
            document_version_id=document_version_id,
            execution_id=execution_id,
            pipeline_profile_revision=pipeline_profile_revision,
            extraction=extraction,
            processing_revision_id=processing_revision_id,
        )
        indexed = self._lexical_index.index_units(
            organization_id=organization_id,
            document_id=document_id,
            document_version_id=document_version_id,
            execution_id=execution_id,
            pipeline_profile_revision=pipeline_profile_revision,
            units=extraction.content_units,
            language_config=language_config,
        )
        return IngestionPostProcessingResult(persistence=persisted, lexical_index=indexed)
