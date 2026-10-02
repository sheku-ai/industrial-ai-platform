from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.ingestion_adapter_resolver import DeploymentEdition, IngestionAdapterResolver
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_contracts import (
    AcquiredSource,
    IngestionContractError,
    IngestionRequest,
    ResolvedAdapterConfiguration,
)
from app.services.ingestion_pipeline import IngestionPipelineCoordinator, IngestionPipelineInput


class Control:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled
        self.pulses = 0

    def pulse(self) -> None:
        self.pulses += 1

    def is_cancellation_requested(self) -> bool:
        return self.cancelled

    def raise_if_cancellation_requested(self) -> None:
        if self.cancelled:
            raise RuntimeError("cancelled")


def make_input(path: Path) -> IngestionPipelineInput:
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    version_id = uuid4()
    reference = "object://source/input.txt"
    request = IngestionRequest(
        organization_id=uuid4(),
        execution_id=uuid4(),
        subject_type="document_version",
        subject_id=version_id,
        document_id=uuid4(),
        document_version_id=version_id,
        source_reference=reference,
        declared_media_type="text/plain",
        original_file_name=path.name,
        content_length=len(payload),
        checksum_sha256=digest,
        adapter_hint="platform.text.plain",
    )
    source = AcquiredSource(
        source_reference=reference,
        local_path=str(path),
        detected_media_type="text/plain",
        content_length=len(payload),
        checksum_sha256=digest,
    )
    configuration = ResolvedAdapterConfiguration(
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
        settings={},
    )
    return IngestionPipelineInput(
        request=request,
        source=source,
        configuration=configuration,
        deployment_edition=DeploymentEdition.COMMUNITY,
    )


def service() -> IngestionPipelineCoordinator:
    return IngestionPipelineCoordinator(IngestionAdapterResolver([PlainTextIngestionAdapter()]))


def test_pipeline_resolves_validates_and_extracts(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("first\n\nsecond", encoding="utf-8")
    result = service().execute(make_input(path), Control())
    assert result.validation.accepted is True
    assert [unit.text for unit in result.extraction.content_units] == ["first", "second"]


def test_pipeline_rejects_source_reference_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    item = make_input(path)
    other = AcquiredSource(
        source_reference="object://source/other.txt",
        local_path=item.source.local_path,
        detected_media_type=item.source.detected_media_type,
        content_length=item.source.content_length,
        checksum_sha256=item.source.checksum_sha256,
    )
    with pytest.raises(IngestionContractError, match="source reference mismatch"):
        service().execute(
            IngestionPipelineInput(item.request, other, item.configuration, item.deployment_edition), Control()
        )


def test_pipeline_rejects_configuration_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    item = make_input(path)
    bad = ResolvedAdapterConfiguration(
        adapter_key="platform.other",
        adapter_version="1.0.0",
        pipeline_profile_revision="rev-1",
    )
    with pytest.raises(IngestionContractError, match="configuration adapter mismatch"):
        service().execute(IngestionPipelineInput(item.request, item.source, bad, item.deployment_edition), Control())


def test_pipeline_checks_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cancelled"):
        service().execute(make_input(path), Control(cancelled=True))


def test_pipeline_has_no_persistence_or_provider_state() -> None:
    coordinator = service()
    assert not hasattr(coordinator, "session")
    assert not hasattr(coordinator, "repository")
    assert not hasattr(coordinator, "provider")
