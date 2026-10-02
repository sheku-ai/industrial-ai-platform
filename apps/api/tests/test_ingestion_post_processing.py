from hashlib import sha256
from uuid import uuid4

from app.services.document_content_persistence import (
    DocumentContentPersistenceResult,
    DocumentContentPersistenceService,
)
from app.services.ingestion_contracts import ContentUnit, ExtractionResult, IngestionUnitType
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.lexical_indexing import LexicalIndexResult, LexicalIndexService


class ContentRepo:
    def __init__(self, calls):
        self.calls = calls

    def replace_document_version_content(self, batch):
        self.calls.append("persist")
        return DocumentContentPersistenceResult(
            inserted_units=len(batch.units),
            replaced_units=0,
            unchanged_units=0,
            idempotency_key=batch.idempotency_key,
        )


class LexicalRepo:
    def __init__(self, calls):
        self.calls = calls

    def replace_document_version_index(self, batch):
        self.calls.append("index")
        return LexicalIndexResult(
            indexed_documents=len(batch.documents),
            unchanged_documents=0,
            idempotency_key=batch.idempotency_key,
        )


def extraction():
    text = "alpha beta"
    digest = sha256(text.encode()).hexdigest()
    unit = ContentUnit(
        unit_key="unit:0",
        ordinal=0,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=digest,
        text=text,
    )
    return ExtractionResult(
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        detected_media_type="text/plain",
        detected_format="plain_text",
        content_units=(unit,),
    )


def test_persists_before_lexical_indexing():
    calls = []
    service = IngestionPostProcessingService(
        DocumentContentPersistenceService(ContentRepo(calls)),
        LexicalIndexService(LexicalRepo(calls)),
    )

    result = service.process(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        execution_id=uuid4(),
        pipeline_profile_revision="rev-1",
        extraction=extraction(),
    )

    assert calls == ["persist", "index"]
    assert result.persistence.inserted_units == 1
    assert result.lexical_index.indexed_documents == 1


def test_service_has_no_semantic_provider_state():
    service = IngestionPostProcessingService(
        DocumentContentPersistenceService(ContentRepo([])),
        LexicalIndexService(LexicalRepo([])),
    )
    assert not hasattr(service, "vector_store")
    assert not hasattr(service, "embedding_model")
    assert not hasattr(service, "llm")
