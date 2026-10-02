from dataclasses import replace

from app.services.ingestion_adapters.ocr_pdf import OcrPdfIngestionAdapter


class SegmentedPdfIngestionAdapter(OcrPdfIngestionAdapter):
    def extract(self, source, configuration, control):
        result = super().extract(source, configuration, control)
        units = tuple(
            replace(unit, ordinal=int(unit.source_locator.get("page_number", 1)) - 1) for unit in result.content_units
        )
        metrics = dict(result.metrics)
        page_count = int(metrics.get("page_count", len(units)))
        page_start = int(metrics.get("page_start", 0))
        page_end = int(metrics.get("page_end_exclusive", page_count))
        metrics["partial_segment_update"] = page_start > 0 or page_end < page_count
        return replace(result, content_units=units, metrics=metrics)
