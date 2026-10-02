from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition, IngestionAdapterResolver
from app.services.ingestion_adapters.ndjson import NdjsonIngestionAdapter
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_configuration import IngestionConfigurationService, IngestionPipelineProfileSnapshot
from app.services.ingestion_contracts import AcquiredSource
from app.services.ingestion_pipeline import IngestionPipelineCoordinator
from app.services.runtime_worker import RuntimeWorkItem


class Heartbeat:
    def pulse(self):
        return None


class Acquisition:
    def __init__(self, source: AcquiredSource) -> None:
        self.source = source

    def acquire(self, organization_id, source_reference, *, execution_id, attempt_number):
        del organization_id, source_reference, execution_id, attempt_number
        return self.source


class Repository:
    def __init__(self, profile: IngestionPipelineProfileSnapshot) -> None:
        self.profile = profile

    def get_pipeline_profile(self, organization_id, profile_id):
        assert organization_id == self.profile.organization_id
        assert profile_id == self.profile.profile_id
        return self.profile


class PostProcessing:
    def process(self, **kwargs):
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


def test_runtime_uses_detected_media_type_before_default_adapter(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"name":"alpha"}\n', encoding="utf-8")
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    organization_id = uuid4()
    profile_id = uuid4()
    version_id = uuid4()
    source_reference = "object://source/input.ndjson"

    source = AcquiredSource(
        source_reference=source_reference,
        local_path=str(path),
        detected_media_type="application/x-ndjson",
        content_length=len(payload),
        checksum_sha256=digest,
    )
    profile = IngestionPipelineProfileSnapshot(
        profile_id=profile_id,
        organization_id=organization_id,
        revision="rev-1",
        enabled=True,
        deployment_edition=DeploymentEdition.COMMUNITY,
        default_adapter_key="platform.text.plain",
        adapter_policies=(
            AdapterPolicy(adapter_key="platform.text.plain"),
            AdapterPolicy(adapter_key="platform.ndjson.generic"),
        ),
        adapter_versions={
            "platform.text.plain": "1.0.0",
            "platform.ndjson.generic": "1.0.0",
        },
        adapter_settings={
            "platform.text.plain": {},
            "platform.ndjson.generic": {},
        },
    )
    adapter = DocumentIngestionRuntimeAdapter(
        Acquisition(source),
        IngestionConfigurationService(Repository(profile)),
        IngestionPipelineCoordinator(
            IngestionAdapterResolver(
                [PlainTextIngestionAdapter(), NdjsonIngestionAdapter()]
            )
        ),
        PostProcessing(),
    )
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
            "declared_media_type": "application/octet-stream",
            "original_file_name": path.name,
            "content_length": len(payload),
            "checksum_sha256": digest,
            "pipeline_profile_id": str(profile_id),
            "metadata": {},
            "options": {},
        },
        policy_snapshot={},
    )

    result = adapter.execute(item, Heartbeat())

    assert result.metrics["adapter_key"] == "platform.ndjson.generic"
    assert result.metrics["detected_media_type"] == "application/x-ndjson"
    assert result.metrics["persistence_connected"] is True
    assert result.metrics["lexical_index_connected"] is True
