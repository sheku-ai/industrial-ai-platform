from uuid import uuid4

from app.services.markitdown_provider import MarkItDownProvider, MarkItDownProviderSettings
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    CapabilityState,
    DocumentExtractionRequest,
    MultimodalStatus,
    ProcessingProfile,
)


def make_request() -> DocumentExtractionRequest:
    return DocumentExtractionRequest(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_reference="memory://document.docx",
        original_file_name="document.docx",
        declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        checksum_sha256="a" * 64,
        profile=ProcessingProfile.ECONOMY,
        policy=DEFAULT_PROCESSING_POLICIES[ProcessingProfile.ECONOMY],
    )


def test_provider_is_disabled_by_default() -> None:
    provider = MarkItDownProvider()

    assert provider.capability.state == CapabilityState.DISABLED
    result = provider.extract(make_request(), b"payload")
    assert result.status == MultimodalStatus.SKIPPED
    assert result.error_code == "provider_disabled"


def test_enabled_provider_reports_unavailable_when_package_missing(monkeypatch) -> None:
    monkeypatch.setattr(MarkItDownProvider, "package_available", staticmethod(lambda: False))
    provider = MarkItDownProvider(MarkItDownProviderSettings(enabled=True))

    assert provider.capability.state == CapabilityState.UNAVAILABLE
    result = provider.extract(make_request(), b"payload")
    assert result.status == MultimodalStatus.SKIPPED
    assert result.error_code == "provider_unavailable"


def test_source_budget_is_enforced_before_execution(monkeypatch) -> None:
    monkeypatch.setattr(MarkItDownProvider, "package_available", staticmethod(lambda: True))
    provider = MarkItDownProvider(
        MarkItDownProviderSettings(enabled=True, max_source_bytes=4)
    )

    result = provider.extract(make_request(), b"12345")
    assert result.status == MultimodalStatus.FAILED
    assert result.error_code == "source_too_large"


def test_capability_declares_isolation_and_no_plugins(monkeypatch) -> None:
    monkeypatch.setattr(MarkItDownProvider, "package_available", staticmethod(lambda: True))
    capability = MarkItDownProvider(MarkItDownProviderSettings(enabled=True)).capability

    assert capability.state == CapabilityState.AVAILABLE
    assert capability.details["isolated_subprocess"] is True
    assert capability.details["plugins_enabled"] is False
    assert capability.details["network_allowed"] is False
    assert capability.requires_gpu is False
