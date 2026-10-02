from __future__ import annotations

import io
import time

from pypdf import PdfReader

from app.services.multimodal_contracts import (
    CapabilityState,
    DocumentExtractionRequest,
    DocumentExtractionResult,
    MultimodalStatus,
    ProviderCapability,
)


class NativePdfProvider:
    provider_key = "native-pdf"

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_key=self.provider_key,
            capability="document_extraction",
            state=CapabilityState.AVAILABLE,
            local=True,
            requires_gpu=False,
            details={
                "ocr": False,
                "network_allowed": False,
                "protected_document_detection": True,
                "password_decryption": True,
            },
        )

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult:
        if len(payload) > request.policy.budget.max_source_bytes:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="source_too_large",
                error_message="source exceeds the configured extraction budget",
            )
        started = time.perf_counter()
        try:
            reader = PdfReader(io.BytesIO(payload))
        except Exception as exc:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="invalid_pdf",
                error_message=str(exc),
            )

        protected_retry = False
        if reader.is_encrypted:
            password = request.metadata.get("document_password")
            if not isinstance(password, str) or not password:
                return DocumentExtractionResult(
                    status=MultimodalStatus.PARTIAL,
                    provider_key=self.provider_key,
                    error_code="password_required",
                    error_message="encrypted PDF requires human review before processing",
                    metrics={
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "protected_document": True,
                        "review_required": True,
                        "detected_format": "pdf",
                        "ocr_used": False,
                        "llm_used": False,
                        "network_used": False,
                    },
                )
            try:
                decrypted = reader.decrypt(password)
            except Exception:
                decrypted = 0
            if not decrypted:
                return DocumentExtractionResult(
                    status=MultimodalStatus.PARTIAL,
                    provider_key=self.provider_key,
                    error_code="invalid_password",
                    error_message="the supplied document password was not accepted",
                    metrics={
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "protected_document": True,
                        "review_required": True,
                        "detected_format": "pdf",
                        "password_value_logged": False,
                    },
                )
            protected_retry = True

        if len(reader.pages) > request.policy.budget.max_pages:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="page_limit_exceeded",
                error_message="PDF exceeds the configured page budget",
            )
        page_blocks = []
        empty_pages = 0
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if not text:
                empty_pages += 1
            else:
                page_blocks.append(f"## Page {index}\n\n{text}")
        markdown = "\n\n".join(page_blocks).strip()
        return DocumentExtractionResult(
            status=MultimodalStatus.SUCCEEDED if markdown else MultimodalStatus.PARTIAL,
            markdown=markdown,
            provider_key=self.provider_key,
            error_code=None if markdown else "no_extractable_text",
            error_message=None if markdown else "PDF may require OCR",
            metrics={
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "page_count": len(reader.pages),
                "empty_page_count": empty_pages,
                "markdown_chars": len(markdown),
                "protected_document_retry": protected_retry,
                "password_value_logged": False,
                "ocr_used": False,
                "llm_used": False,
                "network_used": False,
            },
        )
