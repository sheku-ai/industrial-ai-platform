from __future__ import annotations

from app.services.runtime_worker import RuntimeAdapterResult


class SourceInspectionRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, acquisition, inspection) -> None:
        self._delegate = delegate
        self._acquisition = acquisition
        self._inspection = inspection

    def execute(self, item, heartbeat) -> RuntimeAdapterResult:
        source_reference = str(item.input_payload.get("source_reference") or "")
        handle = self._acquisition.open_handle(source_reference)
        inspection = self._inspection.inspect(
            content_length=handle.content_length,
            detected_media_type=handle.detected_media_type,
            options=item.input_payload.get("options") or {},
        )
        result = self._delegate.execute(item, heartbeat)
        metrics = dict(result.metrics)
        metrics.update(
            {
                "source_inspection_connected": True,
                "source_execution_class": inspection.execution_class.value,
                "source_complexity_reasons": list(inspection.reasons),
                "source_content_length": inspection.content_length,
                "source_page_count_hint": inspection.page_count_hint,
                "source_requires_ocr_hint": inspection.requires_ocr_hint,
            }
        )
        return RuntimeAdapterResult(metrics=metrics)
