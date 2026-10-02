from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.document_content_persistence import DocumentContentWriteBatch
from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.ingestion_contracts import (
    AcquiredSource,
    ContentUnit,
    ExtractionResult,
    IngestionUnitType,
)
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeWorkItem


class Heartbeat:
    def __init__(self, fail_after=None):
        self.calls = 0
        self.fail_after = fail_after

    def checkpoint(self):
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RuntimeLeaseLost("lost")

    def pulse(self):
        return None


class Acquisition:
    def __init__(self, source):
        self.source = source

    def acquire(self, *args, **kwargs):
        return self.source


class Configuration:
    def __init__(self, profile):
        self.profile = profile

    def get_profile(self, organization_id, profile_id):
        return self.profile

    def resolve_for_adapter(self, profile, adapter_key):
        return SimpleNamespace(adapter_configuration={})


class Pipeline:
    def __init__(self, extraction):
        self.extraction = extraction

    def resolve_adapter(self, *args, **kwargs):
        return SimpleNamespace(adapter=SimpleNamespace(adapter_key=self.extraction.adapter_key))

    def execute(self, *args, **kwargs):
        return SimpleNamespace(extraction=self.extraction)


class PostProcessing:
    def __init__(self):
        self.kwargs = None

    def process(self, **kwargs):
        self.kwargs = kwargs
        count = len(kwargs["extraction"].content_units)
        return SimpleNamespace(
            persistence=SimpleNamespace(
                inserted_units=count,
                replaced_units=0,
                unchanged_units=0,
            ),
            lexical_index=SimpleNamespace(
                indexed_documents=count,
                unchanged_documents=0,
            ),
        )


class ProcessingRevisions:
    def __init__(self):
        self.revision_id = uuid4()
        self.started = []
        self.completed = []
        self.failed = []

    def start(self, **kwargs):
        self.started.append(kwargs)
        return self.revision_id

    def complete(self, **kwargs):
        self.completed.append(kwargs)

    def fail(self, **kwargs):
        self.failed.append(kwargs)


def _fixture():
    organization_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    profile_id = uuid4()
    attempt_id = uuid4()
    payload = b"content"
    digest = sha256(payload).hexdigest()
    unit = ContentUnit(
        unit_key="u:0",
        ordinal=0,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=digest,
        text="content",
    )
    extraction = ExtractionResult(
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        detected_media_type="text/plain",
        detected_format="plain_text",
        content_units=(unit,),
    )
    source = AcquiredSource(
        source_reference="object://input.txt",
        local_path="input.txt",
        detected_media_type="text/plain",
        content_length=len(payload),
        checksum_sha256=digest,
    )
    profile = SimpleNamespace(
        revision="rev-1",
        deployment_edition="community",
        adapter_policies=(),
    )
    item = RuntimeWorkItem(
        organization_id=organization_id,
        execution_id=uuid4(),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=document_version_id,
        attempt_id=attempt_id,
        attempt_number=1,
        lease_token=uuid4(),
        input_payload={
            "document_id": str(document_id),
            "document_version_id": str(document_version_id),
            "source_reference": source.source_reference,
            "declared_media_type": "text/plain",
            "original_file_name": "input.txt",
            "content_length": len(payload),
            "checksum_sha256": digest,
            "pipeline_profile_id": str(profile_id),
            "metadata": {},
            "options": {},
        },
        policy_snapshot={"policy_revision": "1"},
    )
    post = PostProcessing()
    revisions = ProcessingRevisions()
    adapter = DocumentIngestionRuntimeAdapter(
        Acquisition(source),
        Configuration(profile),
        Pipeline(extraction),
        post,
        processing_revisions=revisions,
    )
    return adapter, item, post, revisions


def test_adapter_creates_propagates_and_completes_processing_revision():
    adapter, item, post, revisions = _fixture()

    result = adapter.execute(item, Heartbeat())

    assert len(revisions.started) == 1
    assert revisions.started[0]["runtime_attempt_id"] == item.attempt_id
    assert post.kwargs["processing_revision_id"] == revisions.revision_id
    assert revisions.completed[0]["content_unit_count"] == 1
    assert revisions.completed[0]["chunk_count"] == 1
    assert result.metrics["processing_revision_connected"] is True
    assert result.metrics["processing_revision_id"] == str(revisions.revision_id)


def test_adapter_marks_revision_abandoned_when_lease_is_lost_after_start():
    adapter, item, _, revisions = _fixture()

    with pytest.raises(RuntimeLeaseLost):
        adapter.execute(item, Heartbeat(fail_after=3))

    assert revisions.failed == [
        {
            "organization_id": item.organization_id,
            "runtime_execution_id": item.execution_id,
            "runtime_attempt_id": item.attempt_id,
            "status": "abandoned",
        }
    ]
    assert revisions.completed == []


def test_content_batch_revision_identity_is_retry_stable():
    revision_id = uuid4()
    unit = ContentUnit(
        unit_key="u:0",
        ordinal=0,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash="a" * 64,
        text="content",
    )
    values = dict(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
        units=(unit,),
        processing_revision_id=revision_id,
    )

    first = DocumentContentWriteBatch(execution_id=uuid4(), **values)
    second = DocumentContentWriteBatch(execution_id=uuid4(), **values)

    assert first.idempotency_key == second.idempotency_key
    assert str(revision_id) in first.idempotency_key
