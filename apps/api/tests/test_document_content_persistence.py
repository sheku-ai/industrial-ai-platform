from hashlib import sha256
from uuid import uuid4

import pytest

from app.services.document_content_persistence import (
    DocumentContentPersistenceResult,
    DocumentContentPersistenceService,
    DocumentContentWriteBatch,
)
from app.services.ingestion_contracts import ContentUnit, ExtractionResult, IngestionContractError, IngestionUnitType


def content_unit(index, text):
    digest = sha256(text.encode()).hexdigest()
    return ContentUnit(
        unit_key=f"u:{index}:{digest[:8]}",
        ordinal=index,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=digest,
        text=text,
    )


def extraction_result(units):
    return ExtractionResult(
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        detected_media_type="text/plain",
        detected_format="plain_text",
        content_units=tuple(units),
    )


class Repo:
    def __init__(self):
        self.batch = None

    def replace_document_version_content(self, batch):
        self.batch = batch
        return DocumentContentPersistenceResult(
            inserted_units=len(batch.units),
            replaced_units=0,
            unchanged_units=0,
            idempotency_key=batch.idempotency_key,
        )


def test_persists_units():
    repo = Repo()
    result = DocumentContentPersistenceService(repo).persist_extraction(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        execution_id=uuid4(),
        pipeline_profile_revision="rev-1",
        extraction=extraction_result([content_unit(0, "a"), content_unit(1, "b")]),
    )
    assert result.inserted_units == 2
    assert repo.batch.units[1].text == "b"


def test_idempotency_key_is_retry_stable():
    values = dict(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
        units=(content_unit(0, "a"),),
    )
    first = DocumentContentWriteBatch(execution_id=uuid4(), **values)
    second = DocumentContentWriteBatch(execution_id=uuid4(), **values)
    assert first.idempotency_key == second.idempotency_key


def test_requires_unique_ordinals():
    with pytest.raises(IngestionContractError, match="unique"):
        DocumentContentWriteBatch(
            organization_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            execution_id=uuid4(),
            adapter_key="platform.text.plain",
            adapter_version="1.0.0",
            pipeline_profile_revision="rev-1",
            units=(content_unit(0, "a"), content_unit(0, "b")),
        )
