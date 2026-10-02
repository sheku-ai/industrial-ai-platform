from __future__ import annotations

from dataclasses import dataclass

from app.services.markitdown_provider import MarkItDownProvider
from app.services.multimodal_contracts import (
    DocumentExtractionProvider,
    DocumentExtractionRequest,
    DocumentExtractionResult,
    MultimodalStatus,
)
from app.services.native_email_provider import NativeEmailProvider
from app.services.native_pdf_provider import NativePdfProvider
from app.services.source_compatibility import resolve_source_format


@dataclass(frozen=True)
class ProviderAttempt:
    provider_key: str
    status: str
    error_code: str | None


_REVIEW_REQUIRED_CODES = {
    "password_required",
    "encrypted_document",
    "encrypted_container",
    "unsupported_encryption",
    "corrupted_or_encrypted",
}


class RichDocumentAdapter:
    def __init__(
        self,
        *,
        native_pdf: NativePdfProvider | None = None,
        native_email: NativeEmailProvider | None = None,
        markitdown: MarkItDownProvider | None = None,
    ) -> None:
        self.native_pdf = native_pdf or NativePdfProvider()
        self.native_email = native_email or NativeEmailProvider()
        self.markitdown = markitdown or MarkItDownProvider()

    def provider_chain(self, request: DocumentExtractionRequest) -> tuple[DocumentExtractionProvider, ...]:
        source_format = resolve_source_format(request.original_file_name, request.declared_media_type)
        if source_format.key == "pdf":
            return (self.native_pdf, self.markitdown)
        if source_format.key == "email-eml":
            return (self.native_email, self.markitdown)
        if source_format.key in {
            "word-openxml",
            "word-legacy",
            "open-document-text",
            "rich-text",
            "presentation-openxml",
            "presentation-legacy",
            "open-document-presentation",
            "epub",
            "email-msg",
            "image-raster",
        }:
            return (self.markitdown,)
        return ()

    @staticmethod
    def _acceptable(result: DocumentExtractionResult) -> bool:
        return result.status == MultimodalStatus.SUCCEEDED and bool(result.markdown.strip())

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult:
        chain = self.provider_chain(request)
        if not chain:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key="rich-document",
                error_code="unsupported_rich_document_format",
                error_message="no rich-document provider chain is configured for this format",
            )

        attempts: list[ProviderAttempt] = []
        best_partial: DocumentExtractionResult | None = None
        for provider in chain:
            result = provider.extract(request, payload)
            attempts.append(
                ProviderAttempt(
                    provider_key=result.provider_key or "unknown",
                    status=result.status.value,
                    error_code=result.error_code,
                )
            )
            if result.error_code in _REVIEW_REQUIRED_CODES:
                return DocumentExtractionResult(
                    status=MultimodalStatus.PARTIAL,
                    markdown=result.markdown,
                    images=result.images,
                    metrics={
                        **dict(result.metrics),
                        "review_required": True,
                        "provider_attempts": [attempt.__dict__ for attempt in attempts],
                        "fallback_stopped": True,
                    },
                    provider_key=result.provider_key,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )
            if self._acceptable(result):
                metrics = dict(result.metrics)
                metrics.update(
                    {
                        "selected_provider": result.provider_key,
                        "provider_attempts": [attempt.__dict__ for attempt in attempts],
                        "fallback_used": len(attempts) > 1,
                    }
                )
                return DocumentExtractionResult(
                    status=result.status,
                    markdown=result.markdown,
                    images=result.images,
                    metrics=metrics,
                    provider_key=result.provider_key,
                )
            if result.status == MultimodalStatus.PARTIAL and result.markdown.strip():
                best_partial = result
            if result.status == MultimodalStatus.RETRYABLE:
                return DocumentExtractionResult(
                    status=result.status,
                    markdown=result.markdown,
                    images=result.images,
                    metrics={
                        **dict(result.metrics),
                        "provider_attempts": [attempt.__dict__ for attempt in attempts],
                    },
                    provider_key=result.provider_key,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        if best_partial is not None:
            return DocumentExtractionResult(
                status=MultimodalStatus.PARTIAL,
                markdown=best_partial.markdown,
                images=best_partial.images,
                metrics={
                    **dict(best_partial.metrics),
                    "selected_provider": best_partial.provider_key,
                    "provider_attempts": [attempt.__dict__ for attempt in attempts],
                    "fallback_used": len(attempts) > 1,
                },
                provider_key=best_partial.provider_key,
                error_code=best_partial.error_code,
                error_message=best_partial.error_message,
            )

        return DocumentExtractionResult(
            status=MultimodalStatus.FAILED,
            provider_key="rich-document",
            error_code="all_providers_failed",
            error_message="all configured rich-document providers failed or were unavailable",
            metrics={"provider_attempts": [attempt.__dict__ for attempt in attempts]},
        )
