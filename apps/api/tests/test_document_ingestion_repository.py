from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from app.repositories.document_ingestion import (
    SqlAlchemyDocumentIngestionRepository,
    _matches,
    _text,
    _values,
)
from app.services.document_content_persistence import DocumentContentWriteBatch
from app.services.ingestion_contracts import ContentUnit, IngestionUnitType


def make_unit(text=None, structured_data=None):
    raw = text or repr(structured_data)
    digest = sha256(raw.encode()).hexdigest()
    return ContentUnit(
        unit_key="unit:0",
        ordinal=0,
        unit_type=IngestionUnitType.TEXT_SECTION if text else IngestionUnitType.ROW,
        content_hash=digest,
        text=text,
        structured_data=structured_data,
        source_locator={"page": 1},
        attributes={"source": "test"},
    )


def make_batch(unit):
    return DocumentContentWriteBatch(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        execution_id=uuid4(),
        adapter_key="platform.test",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
        units=(unit,),
    )


def test_maps_text_unit_to_existing_chunk_model_fields():
    unit = make_unit(text="alpha beta")
    batch = make_batch(unit)
    values = _values(batch, unit)

    assert values["chunk_index"] == 0
    assert values["chunk_key"] == "unit:0"
    assert values["text"] == "alpha beta"
    assert values["content_type"] == "text_section"
    assert values["section_ref"] == {"page": 1}
    assert values["metadata_json"] == {"source": "test"}
    assert values["status"] == "created"


def test_serializes_structured_unit_deterministically():
    unit = make_unit(structured_data={"z": 2, "a": "one"})
    assert _text(unit) == '{"a": "one", "z": 2}'


def test_chunk_match_ignores_retry_execution_id():
    unit = make_unit(text="alpha beta")
    first = _values(make_batch(unit), unit)
    second = _values(make_batch(unit), unit)
    row = SimpleNamespace(**first)
    row.status = "indexed"

    assert first["provenance"]["execution_id"] != second["provenance"]["execution_id"]
    assert _matches(row, second) is True


def test_chunk_match_detects_pipeline_revision_change():
    unit = make_unit(text="alpha beta")
    first_batch = make_batch(unit)
    second_batch = DocumentContentWriteBatch(
        organization_id=first_batch.organization_id,
        document_id=first_batch.document_id,
        document_version_id=first_batch.document_version_id,
        execution_id=uuid4(),
        adapter_key=first_batch.adapter_key,
        adapter_version=first_batch.adapter_version,
        pipeline_profile_revision="rev-2",
        units=first_batch.units,
    )
    row = SimpleNamespace(**_values(first_batch, unit))

    assert _matches(row, _values(second_batch, unit)) is False


def test_repository_does_not_commit_or_rollback():
    class Session:
        pass

    repository = SqlAlchemyDocumentIngestionRepository(Session())
    assert not hasattr(repository, "commit")
    assert not hasattr(repository, "rollback")
