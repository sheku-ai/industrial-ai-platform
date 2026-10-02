from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition, IngestionAdapterResolver
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_configuration import IngestionConfigurationService, IngestionPipelineProfileSnapshot
from app.services.ingestion_contracts import AcquiredSource, IngestionContractError
from app.services.ingestion_pipeline import IngestionPipelineCoordinator
from app.services.runtime_worker import RuntimeWorkItem


class Heartbeat:
    def __init__(self) -> None:
        self.pulses = 0

    def pulse(self):
        self.pulses += 1
        return None


class Acquisition:
    def __init__(self, source: AcquiredSource) -> None:
        self.source = source
        self.calls = 0

    def acquire(self, organization_id, source_reference, *, execution_id, attempt_number):
        del organization_id, execution_id, attempt_number
        self.calls += 1
        assert source_reference == self.source.source_reference
        return self.source


class Repository:
    def __init__(self, snapshot: IngestionPipelineProfileSnapshot) -> None:
        self.snapshot = snapshot

    def get_pipeline_profile(self, organization_id, profile_id):
        assert organization_id == self.snapshot.organization_id
        assert profile_id == self.snapshot.profile_id
        return self.snapshot


class PostProcessing:
    def __init__(self) -> None:
        self.calls = 0

    def process(self, **kwargs):
        self.calls += 1
        assert kwargs["pipeline_profile_revision"] == "rev-1"
        return SimpleNamespace(
            persistence=SimpleNamespace(
                inserted_units=len(kwargs["extraction"].content_units),
                replaced_units=0,
                unchanged_units=0,
            ),
            lexical_index=SimpleNamespace(
                indexed_documents=len(kwargs["extraction"].content_units),
                unchanged_documents=0,
            ),
        )


def build_adapter(path: Path):
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    organization_id = uuid4()
    profile_id = uuid4()
    source_reference = "object://source/input.txt"
    source = AcquiredSource(
        source_reference=source_reference,
        local_path=str(path),
        detected_media_type="text/plain",
        content_length=len(payload),
        checksum_sha256=digest,
    )
    snapshot = IngestionPipelineProfileSnapshot(
        profile_id=profile_id,
        organization_id=organization_id,
        revision="rev-1",
        enabled=True,
        deployment_edition=DeploymentEdition.COMMUNITY,
        default_adapter_key="platform.text.plain",
        adapter_policies=(AdapterPolicy(adapter_key="platform.text.plain"),),
        adapter_versions={"platform.text.plain": "1.0.0"},
        adapter_settings={"platform.text.plain": {}},
    )
    acquisition = Acquisition(source)
    post_processing = PostProcessing()
    adapter = DocumentIngestionRuntimeAdapter(
        acquisition,
        IngestionConfigurationService(Repository(snapshot)),
        IngestionPipelineCoordinator(
            IngestionAdapterResolver([PlainTextIngestionAdapter()])
        ),
        post_processing,
    )
    version_id = uuid4()
    item = RuntimeWorkItem(
        organization_id=organization_id,
        execution_id=uuid4(),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=version_id,
        attempt_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        input_payload={
            "document_id": str(uuid4()),
            "document_version_id": str(version_id),
            "source_reference": source_reference,
            "declared_media_type": "text/plain",
            "original_file_name": path.name,
            "content_length": len(payload),
            "checksum_sha256": digest,
            "pipeline_profile_id": str(profile_id),
            "adapter_hint": "platform.text.plain",
            "metadata": {},
            "options": {},
        },
        policy_snapshot={},
    )
    return adapter, acquisition, post_processing, item


def test_runtime_adapter_executes_pipeline_and_returns_safe_metrics(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("first\n\nsecond", encoding="utf-8")
    adapter, acquisition, post_processing, item = build_adapter(path)
    heartbeat = Heartbeat()

    result = adapter.execute(item, heartbeat)

    assert acquisition.calls == 1
    assert post_processing.calls == 1
    assert result.metrics["adapter_key"] == "platform.text.plain"
    assert result.metrics["content_units"] == 2
    assert result.metrics["persistence_connected"] is True
    assert result.metrics["lexical_index_connected"] is True
    assert result.metrics["semantic_publication_connected"] is False
    assert heartbeat.pulses > 0


def test_runtime_adapter_rejects_wrong_execution_type(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    adapter, _, _, item = build_adapter(path)
    wrong = RuntimeWorkItem(**{**item.__dict__, "execution_type": "other.type"})
    with pytest.raises(IngestionContractError, match="unsupported runtime execution type"):
        adapter.execute(wrong, Heartbeat())


def test_runtime_adapter_rejects_subject_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    adapter, _, _, item = build_adapter(path)
    wrong = RuntimeWorkItem(**{**item.__dict__, "subject_type": "document"})
    with pytest.raises(IngestionContractError, match="document_version subject"):
        adapter.execute(wrong, Heartbeat())


def test_runtime_adapter_rejects_document_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    adapter, _, _, item = build_adapter(path)
    payload = dict(item.input_payload)
    payload["document_version_id"] = str(uuid4())
    wrong = RuntimeWorkItem(**{**item.__dict__, "input_payload": payload})
    with pytest.raises(IngestionContractError, match="runtime subject"):
        adapter.execute(wrong, Heartbeat())


def test_runtime_adapter_has_no_session_or_provider_state(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    adapter, _, _, _ = build_adapter(path)
    assert adapter.execution_type == "document.ingestion"
    assert not hasattr(adapter, "session")
    assert not hasattr(adapter, "provider")
