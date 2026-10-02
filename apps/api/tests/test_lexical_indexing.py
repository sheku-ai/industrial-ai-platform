from hashlib import sha256
from uuid import uuid4

import pytest

from app.services.ingestion_contracts import ContentUnit, IngestionContractError, IngestionUnitType
from app.services.lexical_indexing import LexicalIndexResult, LexicalIndexService


def text_unit(index, text):
    digest = sha256(text.encode()).hexdigest()
    return ContentUnit(
        unit_key=f"text:{index}:{digest[:8]}",
        ordinal=index,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=digest,
        text=text,
    )


def structured_unit(index, data):
    digest = sha256(repr(sorted(data.items())).encode()).hexdigest()
    return ContentUnit(
        unit_key=f"row:{index}:{digest[:8]}",
        ordinal=index,
        unit_type=IngestionUnitType.ROW,
        content_hash=digest,
        structured_data=data,
    )


class Repo:
    def __init__(self):
        self.batch = None

    def replace_document_version_index(self, batch):
        self.batch = batch
        return LexicalIndexResult(
            indexed_documents=len(batch.documents),
            unchanged_documents=0,
            idempotency_key=batch.idempotency_key,
        )


def test_indexes_text_and_structured_units():
    repo = Repo()
    result = LexicalIndexService(repo).index_units(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        execution_id=uuid4(),
        pipeline_profile_revision="rev-1",
        units=(
            text_unit(0, "alpha beta"),
            structured_unit(1, {"name": "gamma", "value": 2}),
        ),
    )
    assert result.indexed_documents == 2
    assert repo.batch.documents[0].search_text == "alpha beta"
    assert repo.batch.documents[1].search_text == "gamma 2"
    assert repo.batch.documents[0].language_config == "simple"


def test_rejects_repository_count_mismatch():
    class BadRepo:
        def replace_document_version_index(self, batch):
            return LexicalIndexResult(
                indexed_documents=0,
                unchanged_documents=0,
                idempotency_key=batch.idempotency_key,
            )

    with pytest.raises(IngestionContractError, match="counts"):
        LexicalIndexService(BadRepo()).index_units(
            organization_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            execution_id=uuid4(),
            pipeline_profile_revision="rev-1",
            units=(text_unit(0, "content"),),
        )


def test_service_has_no_vector_or_model_state():
    service = LexicalIndexService(Repo())
    assert not hasattr(service, "vector_store")
    assert not hasattr(service, "embedding_model")
    assert not hasattr(service, "llm")
