from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.services.ingestion_contracts import (
    AcquiredSource,
    AdapterCapabilities,
    ContentUnit,
    ExtractionResult,
    IngestionContractError,
    IngestionRequest,
    IngestionUnitType,
    ResolvedAdapterConfiguration,
    ValidationIssue,
    ValidationResult,
    adapter_supports_media_type,
    select_adapter_candidates,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


class AdapterA:
    adapter_key = "adapter.a"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"application/pdf"}),
        priority=20,
    )


class AdapterB:
    adapter_key = "adapter.b"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"Application/PDF; charset=binary"}),
        priority=10,
    )


def test_capabilities_normalize_media_types() -> None:
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"Text/Plain; charset=utf-8"}),
    )

    assert capabilities.supported_media_types == frozenset({"text/plain"})


def test_capabilities_require_media_type() -> None:
    with pytest.raises(IngestionContractError, match="at least one supported media type"):
        AdapterCapabilities(supported_media_types=frozenset())


def test_ingestion_request_enforces_document_version_subject() -> None:
    version_id = uuid4()

    request = IngestionRequest(
        organization_id=uuid4(),
        execution_id=uuid4(),
        subject_type="document_version",
        subject_id=version_id,
        document_id=uuid4(),
        document_version_id=version_id,
        source_reference="object://source/1",
        declared_media_type="Text/Plain; charset=utf-8",
        original_file_name="example.txt",
        content_length=12,
        checksum_sha256=SHA_A,
    )

    assert request.declared_media_type == "text/plain"
    assert request.subject_id == request.document_version_id


def test_ingestion_request_rejects_subject_mismatch() -> None:
    with pytest.raises(IngestionContractError, match="subject_id must equal"):
        IngestionRequest(
            organization_id=uuid4(),
            execution_id=uuid4(),
            subject_type="document_version",
            subject_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            source_reference="object://source/1",
            declared_media_type="text/plain",
            original_file_name="example.txt",
        )


def test_ingestion_request_rejects_invalid_checksum() -> None:
    version_id = uuid4()

    with pytest.raises(IngestionContractError, match="lowercase SHA-256"):
        IngestionRequest(
            organization_id=uuid4(),
            execution_id=uuid4(),
            subject_type="document_version",
            subject_id=version_id,
            document_id=uuid4(),
            document_version_id=version_id,
            source_reference="object://source/1",
            declared_media_type="text/plain",
            original_file_name="example.txt",
            checksum_sha256="NOT-A-CHECKSUM",
        )


def test_validation_result_invariants() -> None:
    accepted = ValidationResult(
        accepted=True,
        detected_media_type="application/pdf",
    )
    assert accepted.issues == ()

    rejected = ValidationResult(
        accepted=False,
        detected_media_type="application/octet-stream",
        issues=(ValidationIssue(code="unsupported", message="unsupported content"),),
    )
    assert rejected.accepted is False

    with pytest.raises(IngestionContractError, match="requires at least one issue"):
        ValidationResult(
            accepted=False,
            detected_media_type="application/octet-stream",
        )


def test_content_unit_requires_content_and_valid_hash() -> None:
    with pytest.raises(IngestionContractError, match="requires text or structured_data"):
        ContentUnit(
            unit_key="unit-1",
            ordinal=0,
            unit_type=IngestionUnitType.TEXT_SECTION,
            content_hash=SHA_A,
        )

    with pytest.raises(IngestionContractError, match="lowercase SHA-256"):
        ContentUnit(
            unit_key="unit-1",
            ordinal=0,
            unit_type=IngestionUnitType.TEXT_SECTION,
            content_hash="bad",
            text="content",
        )


def test_extraction_result_requires_unique_unit_keys_and_ordinals() -> None:
    unit_a = ContentUnit(
        unit_key="unit-1",
        ordinal=0,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=SHA_A,
        text="first",
    )
    unit_b_same_key = ContentUnit(
        unit_key="unit-1",
        ordinal=1,
        unit_type=IngestionUnitType.TEXT_SECTION,
        content_hash=SHA_B,
        text="second",
    )

    with pytest.raises(IngestionContractError, match="unit keys must be unique"):
        ExtractionResult(
            adapter_key="adapter.text",
            adapter_version="1.0",
            detected_media_type="text/plain",
            detected_format="plain_text",
            content_units=(unit_a, unit_b_same_key),
        )


def test_contracts_are_frozen() -> None:
    source = AcquiredSource(
        source_reference="object://source/1",
        local_path="workspace/input.bin",
        detected_media_type="application/octet-stream",
        content_length=10,
        checksum_sha256=SHA_A,
    )

    with pytest.raises(FrozenInstanceError):
        source.content_length = 20  # type: ignore[misc]


def test_resolved_configuration_copies_settings() -> None:
    settings = {"mode": "safe"}
    configuration = ResolvedAdapterConfiguration(
        adapter_key="adapter.text",
        adapter_version="1.0",
        pipeline_profile_revision="rev-1",
        settings=settings,
    )
    settings["mode"] = "changed"

    assert configuration.settings["mode"] == "safe"


def test_adapter_capability_matching_is_normalized_and_deterministic() -> None:
    adapters = (AdapterA(), AdapterB())

    assert adapter_supports_media_type(AdapterA(), "Application/PDF") is True
    selected = select_adapter_candidates(adapters, "application/pdf; version=1.7")

    assert [adapter.adapter_key for adapter in selected] == ["adapter.b", "adapter.a"]
