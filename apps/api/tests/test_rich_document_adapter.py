from uuid import uuid4

from app.services.markitdown_provider import MarkItDownProvider, MarkItDownProviderSettings
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    DocumentExtractionRequest,
    DocumentExtractionResult,
    MultimodalStatus,
    ProcessingProfile,
)
from app.services.rich_document_adapter import RichDocumentAdapter


class StubProvider:
    def __init__(self, key: str, result: DocumentExtractionResult) -> None:
        self.provider_key = key
        self.result = result

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult:
        return self.result


def make_request(file_name: str, media_type: str) -> DocumentExtractionRequest:
    return DocumentExtractionRequest(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_reference=f"memory://{file_name}",
        original_file_name=file_name,
        declared_media_type=media_type,
        checksum_sha256="a" * 64,
        profile=ProcessingProfile.ECONOMY,
        policy=DEFAULT_PROCESSING_POLICIES[ProcessingProfile.ECONOMY],
    )


def test_pdf_chain_prefers_native_provider() -> None:
    adapter = RichDocumentAdapter()
    chain = adapter.provider_chain(make_request("document.pdf", "application/pdf"))

    assert [provider.provider_key for provider in chain] == ["native-pdf", "markitdown"]


def test_eml_chain_prefers_native_email_provider() -> None:
    adapter = RichDocumentAdapter()
    chain = adapter.provider_chain(make_request("message.eml", "message/rfc822"))

    assert [provider.provider_key for provider in chain] == ["native-eml", "markitdown"]


def test_docx_chain_uses_markitdown_only() -> None:
    adapter = RichDocumentAdapter()
    chain = adapter.provider_chain(
        make_request(
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    )

    assert [provider.provider_key for provider in chain] == ["markitdown"]


def test_fallback_uses_second_provider_when_first_is_partial() -> None:
    native = StubProvider(
        "native-pdf",
        DocumentExtractionResult(
            status=MultimodalStatus.PARTIAL,
            provider_key="native-pdf",
            error_code="no_extractable_text",
            error_message="requires fallback",
        ),
    )
    fallback = StubProvider(
        "markitdown",
        DocumentExtractionResult(
            status=MultimodalStatus.SUCCEEDED,
            markdown="# Extracted\n\nContent",
            provider_key="markitdown",
        ),
    )
    adapter = RichDocumentAdapter(native_pdf=native, markitdown=fallback)

    result = adapter.extract(make_request("document.pdf", "application/pdf"), b"payload")

    assert result.status == MultimodalStatus.SUCCEEDED
    assert result.provider_key == "markitdown"
    assert result.metrics["fallback_used"] is True
    assert len(result.metrics["provider_attempts"]) == 2


def test_disabled_markitdown_produces_controlled_failure_for_docx() -> None:
    adapter = RichDocumentAdapter(
        markitdown=MarkItDownProvider(MarkItDownProviderSettings(enabled=False))
    )

    result = adapter.extract(
        make_request(
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        b"payload",
    )

    assert result.status == MultimodalStatus.FAILED
    assert result.error_code == "all_providers_failed"
    assert result.metrics["provider_attempts"][0]["error_code"] == "provider_disabled"


def test_unsupported_format_is_rejected() -> None:
    adapter = RichDocumentAdapter()
    result = adapter.extract(make_request("data.parquet", "application/vnd.apache.parquet"), b"payload")

    assert result.status == MultimodalStatus.FAILED
    assert result.error_code == "unsupported_rich_document_format"
