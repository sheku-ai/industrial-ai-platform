from uuid import uuid4

import pytest

from app.services.ingestion_adapter_contracts import (
    BUILTIN_ADAPTER_INVENTORY,
    AdapterCapability,
    AdapterCoupling,
    AdapterDescriptor,
    AdapterExecutionResult,
    AdapterExecutionStatus,
    AdapterInput,
    AdapterKind,
    AdapterRoutingError,
    select_adapter,
)


def test_builtin_inventory_is_generic_and_ai_optional() -> None:
    keys = {descriptor.adapter_key for descriptor in BUILTIN_ADAPTER_INVENTORY}

    assert keys == {"text", "rich-document", "spreadsheet", "ndjson"}
    assert all(descriptor.requires_ai is False for descriptor in BUILTIN_ADAPTER_INVENTORY)
    assert all(descriptor.enabled_by_default is False for descriptor in BUILTIN_ADAPTER_INVENTORY)


def test_text_route_matches_extension_and_media_type() -> None:
    decision = select_adapter(
        BUILTIN_ADAPTER_INVENTORY,
        file_name="source.txt",
        declared_media_type="text/plain",
    )

    assert decision.adapter_key == "text"
    assert decision.reason == "extension_and_media_type"


def test_spreadsheet_route_matches_csv() -> None:
    decision = select_adapter(
        BUILTIN_ADAPTER_INVENTORY,
        file_name="source.csv",
        declared_media_type="text/csv",
    )

    assert decision.adapter_key == "spreadsheet"


def test_ambiguous_route_is_rejected() -> None:
    duplicate = AdapterDescriptor(
        adapter_key="custom-text",
        kind=AdapterKind.TEXT,
        supported_extensions=(".txt",),
        supported_media_types=("text/plain",),
        capabilities=frozenset({AdapterCapability.EXTRACT_TEXT}),
        implementation_asset="custom.py",
    )

    with pytest.raises(AdapterRoutingError, match="multiple"):
        select_adapter(
            (*BUILTIN_ADAPTER_INVENTORY, duplicate),
            file_name="source.txt",
            declared_media_type="text/plain",
        )


def test_unmatched_route_is_rejected() -> None:
    with pytest.raises(AdapterRoutingError, match="no configured"):
        select_adapter(
            BUILTIN_ADAPTER_INVENTORY,
            file_name="source.unknown",
            declared_media_type="application/octet-stream",
        )


def test_ndjson_inventory_exposes_legacy_couplings_for_refactoring() -> None:
    descriptor = next(item for item in BUILTIN_ADAPTER_INVENTORY if item.adapter_key == "ndjson")

    assert AdapterCoupling.DATABASE in descriptor.direct_couplings
    assert AdapterCoupling.VECTOR_STORE in descriptor.direct_couplings
    assert AdapterCoupling.EMBEDDING_PROVIDER in descriptor.direct_couplings
    assert AdapterCapability.LOAD_CHUNKS in descriptor.capabilities


def test_adapter_input_requires_valid_source_contract() -> None:
    request = AdapterInput(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_reference="s3://payload/source.txt",
        original_file_name="source.txt",
        declared_media_type="text/plain",
        checksum_sha256="a" * 64,
        content_length=12,
        idempotency_key="adapter:test",
    )

    assert request.attempt == 1
    assert request.metadata == {}


def test_failed_result_requires_error_code() -> None:
    with pytest.raises(ValueError, match="requires an error_code"):
        AdapterExecutionResult(status=AdapterExecutionStatus.FAILED)


def test_success_result_cannot_include_error_code() -> None:
    with pytest.raises(ValueError, match="cannot include"):
        AdapterExecutionResult(
            status=AdapterExecutionStatus.SUCCEEDED,
            error_code="unexpected",
        )
