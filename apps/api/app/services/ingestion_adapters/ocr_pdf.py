from hashlib import sha256

from pypdf import PdfReader

from app.services.ingestion_adapters.protected_pdf import PasswordAwarePdfIngestionAdapter, _resolve_page_range
from app.services.ingestion_contracts import (
    ContentUnit,
    ExtractionResult,
    ExtractionWarning,
    IngestionContractError,
    IngestionUnitType,
)
from app.services.pdf_ocr_enrichment import PdfOcrEnrichmentService


class OcrPdfIngestionAdapter(PasswordAwarePdfIngestionAdapter):
    def extract(self, source, configuration, control):
        validation = self.validate(source, configuration)
        if not validation.accepted:
            codes = ",".join(issue.code for issue in validation.issues)
            raise IngestionContractError(f"source failed PDF adapter validation: {codes}")

        settings = configuration.settings
        reader = PdfReader(source.local_path, strict=False)
        protected_retry = False
        if reader.is_encrypted:
            password = settings.get("document_password")
            if not isinstance(password, str) or not reader.decrypt(password):
                raise IngestionContractError("protected PDF password was not accepted")
            protected_retry = True

        start, end = _resolve_page_range(settings, len(reader.pages))
        enable_ocr = bool(settings.get("enable_ocr", False))
        max_ocr_pages = max(int(settings.get("max_ocr_pages", 50)), 0)
        enrichment = PdfOcrEnrichmentService() if enable_ocr else None
        units = []
        warnings = []
        ocr_pages = 0
        cache_hits = 0
        failures = 0

        for page_index in range(start, end):
            control.raise_if_cancellation_requested()
            text = (reader.pages[page_index].extract_text() or "").strip()
            attributes = {"pdf_page_index": page_index, "text_layer": bool(text), "protected_retry": protected_retry}

            if not text and enable_ocr and ocr_pages < max_ocr_pages:
                result = enrichment.recognize_page(source.local_path, page_index, settings)
                ocr_pages += 1
                cache_hits += int(result.cache_hit)
                if result.text:
                    text = result.text
                    attributes.update(
                        {
                            "ocr": True,
                            "ocr_confidence": result.confidence,
                            "ocr_language": result.language,
                            "ocr_bounding_boxes": result.bounding_box_count,
                            "ocr_rotation_degrees": result.rotation_degrees,
                        }
                    )
                else:
                    failures += 1
                    warnings.append(
                        ExtractionWarning(
                            code=result.error_code or "ocr_no_text",
                            message=f"page {page_index + 1} OCR did not produce text",
                        )
                    )
            elif not text and enable_ocr and ocr_pages >= max_ocr_pages:
                warnings.append(
                    ExtractionWarning(
                        code="ocr_page_limit_reached", message=f"page {page_index + 1} exceeded max_ocr_pages"
                    )
                )

            if not text:
                warnings.append(
                    ExtractionWarning(
                        code="page_without_text", message=f"page {page_index + 1} did not contain extractable text"
                    )
                )
                control.pulse()
                continue

            digest = sha256(text.encode("utf-8")).hexdigest()
            units.append(
                ContentUnit(
                    unit_key=f"page:{page_index + 1}:{digest[:16]}",
                    ordinal=page_index,
                    unit_type=IngestionUnitType.PAGE,
                    content_hash=digest,
                    text=text,
                    source_locator={"page_number": page_index + 1},
                    attributes=attributes,
                )
            )
            control.pulse()

        if not units:
            message = (
                "PDF page range contains no extractable text after OCR"
                if enable_ocr
                else "PDF page range contains no extractable text; OCR capability is not configured"
            )
            raise IngestionContractError(message)

        return ExtractionResult(
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            detected_media_type=source.detected_media_type,
            detected_format="pdf_ocr_enriched" if ocr_pages else "pdf_text_layer",
            content_units=tuple(units),
            metrics={
                "source_bytes": source.content_length,
                "page_count": len(reader.pages),
                "page_start": start,
                "page_end_exclusive": end,
                "pages_processed": end - start,
                "content_units": len(units),
                "encrypted": protected_retry,
                "protected_document_retry": protected_retry,
                "password_value_persisted": False,
                "ocr_enabled": enable_ocr,
                "ocr_used": ocr_pages > 0,
                "ocr_pages_processed": ocr_pages,
                "ocr_cache_hits": cache_hits,
                "ocr_failures": failures,
                "max_ocr_pages": max_ocr_pages,
            },
            warnings=tuple(warnings),
            quality_observations=(),
        )
