from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.ingestion_contracts import (
    AcquiredSource,
    AdapterCapabilities,
    ContentUnit,
    ExtractionResult,
    ExtractionWarning,
    IngestionContractError,
    IngestionExecutionControl,
    IngestionUnitType,
    ResolvedAdapterConfiguration,
    ValidationIssue,
    ValidationResult,
)


class PdfIngestionAdapter:
    """Deterministic text-layer PDF adapter.

    This adapter extracts the existing PDF text layer page by page. It does not
    perform OCR, execute subprocesses, persist chunks, publish artifacts, access
    runtime state or invoke AI components.
    """

    adapter_key = "platform.pdf.text_layer"
    adapter_version = "1.0.0"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"application/pdf"}),
        priority=100,
        requires_external_binary=False,
        supports_ocr=False,
        supports_structured_output=False,
        supports_cancellation=True,
        community_available=True,
        enterprise_available=True,
    )

    def validate(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        path = Path(source.local_path)

        if source.detected_media_type not in self.capabilities.supported_media_types:
            issues.append(
                ValidationIssue(
                    code="unsupported_media_type",
                    message="detected media type is not supported by the PDF adapter",
                )
            )

        if not path.is_file():
            issues.append(
                ValidationIssue(
                    code="source_not_found",
                    message="acquired source file is not available",
                    retryable=False,
                )
            )
            return ValidationResult(
                accepted=False,
                detected_media_type=source.detected_media_type,
                issues=tuple(issues),
            )

        stat_size = path.stat().st_size
        if stat_size != source.content_length:
            issues.append(
                ValidationIssue(
                    code="content_length_mismatch",
                    message="acquired source length does not match the registered source",
                )
            )

        digest = _sha256_file(path)
        if digest != source.checksum_sha256:
            issues.append(
                ValidationIssue(
                    code="checksum_mismatch",
                    message="acquired source checksum does not match the registered source",
                )
            )

        if stat_size == 0:
            issues.append(
                ValidationIssue(
                    code="empty_content",
                    message="PDF source is empty",
                )
            )
        elif not _has_pdf_signature(path):
            issues.append(
                ValidationIssue(
                    code="invalid_pdf_signature",
                    message="source does not contain a valid PDF signature",
                )
            )

        max_pages = _setting_positive_int(configuration.settings, "max_pages", default=10_000)
        if not issues:
            try:
                reader = PdfReader(str(path), strict=False)
                if reader.is_encrypted:
                    issues.append(
                        ValidationIssue(
                            code="encrypted_pdf",
                            message="encrypted PDF is not supported by the text-layer adapter",
                        )
                    )
                else:
                    page_count = len(reader.pages)
                    if page_count == 0:
                        issues.append(
                            ValidationIssue(
                                code="empty_pdf",
                                message="PDF contains no pages",
                            )
                        )
                    elif page_count > max_pages:
                        issues.append(
                            ValidationIssue(
                                code="page_limit_exceeded",
                                message="PDF exceeds configured page limit",
                            )
                        )
            except (PdfReadError, OSError, ValueError):
                issues.append(
                    ValidationIssue(
                        code="invalid_pdf",
                        message="source cannot be parsed as a PDF document",
                    )
                )

        return ValidationResult(
            accepted=not issues,
            detected_media_type=source.detected_media_type,
            issues=tuple(issues),
        )

    def extract(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
        control: IngestionExecutionControl,
    ) -> ExtractionResult:
        validation = self.validate(source, configuration)
        if not validation.accepted:
            raise IngestionContractError("source failed PDF adapter validation")

        control.raise_if_cancellation_requested()
        control.pulse()

        reader = PdfReader(source.local_path, strict=False)
        min_page_characters = _setting_non_negative_int(
            configuration.settings,
            "min_page_characters",
            default=1,
        )
        include_empty_pages = _setting_bool(
            configuration.settings,
            "include_empty_pages",
            default=False,
        )

        units: list[ContentUnit] = []
        warnings: list[ExtractionWarning] = []
        extracted_characters = 0
        empty_pages = 0

        for page_index, page in enumerate(reader.pages):
            control.raise_if_cancellation_requested()

            try:
                raw_text = page.extract_text() or ""
            except Exception:
                raw_text = ""
                warnings.append(
                    ExtractionWarning(
                        code="page_extract_failed",
                        message=f"text extraction failed for page {page_index + 1}",
                    )
                )

            normalized = _normalize_text(raw_text)
            extracted_characters += len(normalized)

            if len(normalized) < min_page_characters:
                empty_pages += 1
                warnings.append(
                    ExtractionWarning(
                        code="page_without_text",
                        message=f"page {page_index + 1} did not contain sufficient extractable text",
                    )
                )
                if not include_empty_pages:
                    control.pulse()
                    continue

            content_hash = sha256(normalized.encode("utf-8")).hexdigest()
            units.append(
                ContentUnit(
                    unit_key=f"page:{page_index + 1}:{content_hash[:16]}",
                    ordinal=len(units),
                    unit_type=IngestionUnitType.PAGE,
                    content_hash=content_hash,
                    text=normalized if normalized else "[empty page]",
                    source_locator={"page_number": page_index + 1},
                    attributes={
                        "pdf_page_index": page_index,
                        "text_layer": True,
                    },
                )
            )
            control.pulse()

        if not units:
            raise IngestionContractError("PDF contains no extractable text; OCR capability is not configured")

        return ExtractionResult(
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            detected_media_type=source.detected_media_type,
            detected_format="pdf_text_layer",
            content_units=tuple(units),
            proposed_artifacts=(),
            metrics={
                "source_bytes": source.content_length,
                "page_count": len(reader.pages),
                "content_units": len(units),
                "empty_pages": empty_pages,
                "extracted_characters": extracted_characters,
                "encrypted": False,
                "ocr_used": False,
            },
            warnings=tuple(warnings),
            quality_observations=(),
        )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _has_pdf_signature(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip()


def _setting_bool(settings: Any, key: str, *, default: bool) -> bool:
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise IngestionContractError(f"{key} must be a boolean")
    return value


def _setting_positive_int(settings: Any, key: str, *, default: int) -> int:
    value = settings.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IngestionContractError(f"{key} must be a positive integer")
    return value


def _setting_non_negative_int(settings: Any, key: str, *, default: int) -> int:
    value = settings.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IngestionContractError(f"{key} must be a non-negative integer")
    return value
