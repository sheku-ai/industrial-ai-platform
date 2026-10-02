from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from app.repositories.document_content import SqlAlchemyDocumentContentRepository
from app.services.document_content_persistence import DocumentContentWriteBatch
from app.services.ingestion_contracts import ContentUnit, IngestionUnitType


class ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.added = []
        self.executed = []
        self.flush_count = 0

    def scalars(self, statement):
        return ScalarResult(self.existing)

    def add(self, value):
        self.added.append(value)

    def execute(self, statement):
        self.executed.append(statement)

    def flush(self):
        self.flush_count += 1


def _unit(index: int, text: str) -> ContentUnit:
    return ContentUnit(
        unit_key=f"unit:{index}",
        ordinal=index,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=sha256(text.encode()).hexdigest(),
        text=text,
        source_locator={"page": index + 1},
        attributes={"language": "en"},
    )


def _batch(*units, revision_id=None):
    return DocumentContentWriteBatch(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        execution_id=uuid4(),
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
        units=tuple(units),
        processing_revision_id=revision_id,
    )


def test_repository_inserts_chunks_with_processing_revision_identity():
    revision_id = uuid4()
    batch = _batch(_unit(0, "alpha"), _unit(1, "beta"), revision_id=revision_id)
    session = FakeSession()

    result = SqlAlchemyDocumentContentRepository(session).replace_document_version_content(batch)

    assert result.inserted_units == 2
    assert result.replaced_units == 0
    assert result.unchanged_units == 0
    assert session.flush_count == 1
    assert [chunk.processing_revision_id for chunk in session.added] == [revision_id, revision_id]
    assert session.added[0].provenance["execution_id"] == str(batch.execution_id)


def test_repository_updates_existing_materialization_to_new_revision():
    old_revision = uuid4()
    new_revision = uuid4()
    unit = _unit(0, "alpha")
    batch = _batch(unit, revision_id=new_revision)
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=batch.organization_id,
        document_record_id=batch.document_id,
        document_version_id=batch.document_version_id,
        processing_revision_id=old_revision,
        artifact_id=None,
        collection_id=None,
        chunk_index=0,
        chunk_key=unit.unit_key,
        content_hash=unit.content_hash,
        semantic_hash=None,
        text=unit.text,
        content_type=unit.unit_type.value,
        section_ref=dict(unit.source_locator),
        provenance={
            "execution_id": str(batch.execution_id),
            "adapter_key": batch.adapter_key,
            "adapter_version": batch.adapter_version,
            "pipeline_profile_revision": batch.pipeline_profile_revision,
        },
        quality={},
        metadata_json=dict(unit.attributes),
        status="created",
    )
    session = FakeSession([existing])

    result = SqlAlchemyDocumentContentRepository(session).replace_document_version_content(batch)

    assert result.inserted_units == 0
    assert result.replaced_units == 1
    assert result.unchanged_units == 0
    assert existing.processing_revision_id == new_revision


def test_repository_is_idempotent_for_same_revision_and_content():
    revision_id = uuid4()
    unit = _unit(0, "alpha")
    batch = _batch(unit, revision_id=revision_id)
    values = SqlAlchemyDocumentContentRepository._chunk_values(batch, unit)
    existing = SimpleNamespace(id=uuid4(), **values)
    session = FakeSession([existing])

    result = SqlAlchemyDocumentContentRepository(session).replace_document_version_content(batch)

    assert result.inserted_units == 0
    assert result.replaced_units == 0
    assert result.unchanged_units == 1
    assert session.added == []
    assert session.executed == []


def test_repository_removes_stale_materialized_chunks():
    batch = _batch(_unit(0, "alpha"), revision_id=uuid4())
    stale = SimpleNamespace(id=uuid4(), chunk_index=3)
    session = FakeSession([stale])

    result = SqlAlchemyDocumentContentRepository(session).replace_document_version_content(batch)

    assert result.inserted_units == 1
    assert len(session.executed) == 1
