from __future__ import annotations

from email import policy
from email.parser import BytesParser

from app.services.multimodal_contracts import (
    CapabilityState,
    DocumentExtractionRequest,
    DocumentExtractionResult,
    MultimodalStatus,
    ProviderCapability,
)


class NativeEmailProvider:
    provider_key = "native-eml"

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_key=self.provider_key,
            capability="document_extraction",
            state=CapabilityState.AVAILABLE,
            local=True,
            requires_gpu=False,
            details={"attachments_extracted": False, "network_allowed": False},
        )

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult:
        try:
            message = BytesParser(policy=policy.default).parsebytes(payload)
        except Exception as exc:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="invalid_email",
                error_message=str(exc),
            )
        headers = []
        for key in ("Subject", "From", "To", "Cc", "Date"):
            value = message.get(key)
            if value:
                headers.append(f"**{key}:** {value}")
        body = ""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_disposition() == "attachment":
                    continue
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_content()
                    except Exception:
                        body = ""
                    if body:
                        break
        elif message.get_content_type() == "text/plain":
            try:
                body = message.get_content()
            except Exception:
                body = ""
        markdown = "\n\n".join([*headers, body.strip()]).strip()
        return DocumentExtractionResult(
            status=MultimodalStatus.SUCCEEDED if markdown else MultimodalStatus.PARTIAL,
            markdown=markdown,
            provider_key=self.provider_key,
            error_code=None if markdown else "empty_email",
            error_message=None if markdown else "email contains no extractable text",
            metrics={
                "header_count": len(headers),
                "attachment_count": len(list(message.iter_attachments())) if message.is_multipart() else 0,
                "llm_used": False,
                "ocr_used": False,
                "network_used": False,
            },
        )
