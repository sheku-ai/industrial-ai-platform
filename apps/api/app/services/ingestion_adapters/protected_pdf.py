from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.ingestion_adapters.pdf import PdfIngestionAdapter
from app.services.ingestion_contracts import (
    ContentUnit,
    ExtractionResult,
    ExtractionWarning,
    IngestionContractError,
    IngestionUnitType,
    ValidationIssue,
    ValidationResult,
)


class PasswordAwarePdfIngestionAdapter(PdfIngestionAdapter):
    """PDF adapter that accepts approved transient runtime settings."""

    def validate(self, source, configuration) -> ValidationResult:
        issues: list[ValidationIssue] = []
        path = Path(source.local_path)
        if source.detected_media_type not in self.capabilities.supported_media_types:
            issues.append(
                ValidationIssue(
                    code="unsupported_media_type", message="detected media type is not supported by the PDF adapter"
                )
            )
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    code="source_not_found", message="acquired source file is not available", retryable=False
                )
            )
            return ValidationResult(
                accepted=False, detected_media_type=source.detected_media_type, issues=tuple(issues)
            )
        if path.stat().st_size != source.content_length:
            issues.append(
                ValidationIssue(
                    code="content_length_mismatch",
                    message="acquired source length does not match the registered source",
                )
            )
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != source.checksum_sha256:
            issues.append(
                ValidationIssue(
                    code="checksum_mismatch", message="acquired source checksum does not match the registered source"
                )
            )
        if issues:
            return ValidationResult(
                accepted=False, detected_media_type=source.detected_media_type, issues=tuple(issues)
            )
        try:
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted:
                password = configuration.settings.get("document_password")
                if not isinstance(password, str) or not password:
                    issues.append(
                        ValidationIssue(code="password_required", message="encrypted PDF requires human review")
                    )
                elif not reader.decrypt(password):
                    issues.append(
                        ValidationIssue(code="invalid_password", message="supplied document password was not accepted")
                    )
            max_pages = int(configuration.settings.get("max_pages", 10_000))
            if not issues and len(reader.pages) > max_pages:
                issues.append(ValidationIssue(code="page_limit_exceeded", message="PDF exceeds configured page limit"))
            if not issues:
                _resolve_page_range(configuration.settings, len(reader.pages))
        except (PdfReadError, OSError, ValueError, TypeError) as exc:
            issues.append(
                ValidationIssue(code="invalid_pdf", message=f"source cannot be parsed as a PDF document: {exc}")
            )
        return ValidationResult(
            accepted=not issues, detected_media_type=source.detected_media_type, issues=tuple(issues)
        )

    def extract(self, source, configuration, control) -> ExtractionResult:
        validation = self.validate(source, configuration)
        if not validation.accepted:
            codes = ",".join(issue.code for issue in validation.issues)
            raise IngestionContractError(f"source failed PDF adapter validation: {codes}")
        reader = PdfReader(source.local_path, strict=False)
        protected_retry = False
        if reader.is_encrypted:
            password = configuration.settings.get("document_password")
            if not isinstance(password, str) or not reader.decrypt(password):
                raise IngestionContractError("protected PDF password was not accepted")
            protected_retry = True
        page_start, page_end_exclusive = _resolve_page_range(configuration.settings, len(reader.pages))
        units: list[ContentUnit] = []
        warnings: list[ExtractionWarning] = []
        for page_index in range(page_start, page_end_exclusive):
            page = reader.pages[page_index]
            control.raise_if_cancellation_requested()
            text = (page.extract_text() or "").strip()
            if not text:
                warnings.append(
                    ExtractionWarning(
                        code="page_without_text", message=f"page {page_index + 1} did not contain extractable text"
                    )
                )
                control.pulse()
                continue
            content_hash = sha256(text.encode("utf-8")).hexdigest()
            units.append(
                ContentUnit(
                    unit_key=f"page:{page_index + 1}:{content_hash[:16]}",
                    ordinal=len(units),
                    unit_type=IngestionUnitType.PAGE,
                    content_hash=content_hash,
                    text=text,
                    source_locator={"page_number": page_index + 1},
                    attributes={"pdf_page_index": page_index, "text_layer": True, "protected_retry": protected_retry},
                )
            )
            control.pulse()
        if not units:
            raise IngestionContractError(
                "PDF page range contains no extractable text; OCR capability is not configured"
            )
        return ExtractionResult(
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            detected_media_type=source.detected_media_type,
            detected_format="pdf_text_layer",
            content_units=tuple(units),
            metrics={
                "source_bytes": source.content_length,
                "page_count": len(reader.pages),
                "page_start": page_start,
                "page_end_exclusive": page_end_exclusive,
                "pages_processed": page_end_exclusive - page_start,
                "content_units": len(units),
                "encrypted": protected_retry,
                "protected_document_retry": protected_retry,
                "password_value_persisted": False,
                "ocr_used": False,
            },
            warnings=tuple(warnings),
            quality_observations=(),
        )


def _resolve_page_range(settings, page_count: int) -> tuple[int, int]:
    start = int(settings.get("page_start", 0))
    end = int(settings.get("page_end_exclusive", page_count))
    if start < 0 or start >= page_count:
        raise ValueError("page_start is outside the PDF page range")
    if end <= start or end > page_count:
        raise ValueError("page_end_exclusive is outside the PDF page range")
    return start, end
