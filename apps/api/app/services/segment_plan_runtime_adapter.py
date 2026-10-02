from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.services.runtime_worker import RuntimeAdapterResult


class SegmentPlanRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, acquisition, inspection, segment_plans, checkpoints) -> None:
        self._delegate = delegate
        self._acquisition = acquisition
        self._inspection = inspection
        self._segment_plans = segment_plans
        self._checkpoints = checkpoints

    def execute(self, item, heartbeat) -> RuntimeAdapterResult:
        source_reference = str(item.input_payload.get("source_reference") or "")
        options = dict(item.input_payload.get("options") or {})
        handle = self._acquisition.open_handle(source_reference)
        inspection = self._inspection.inspect(
            content_length=handle.content_length,
            detected_media_type=handle.detected_media_type,
            options=options,
        )
        checksum = handle.checksum_sha256 or str(item.input_payload.get("checksum_sha256") or "")
        if len(checksum) != 64:
            raise ValueError("segment planning requires a source checksum")
        pages_per_segment = options.get("pages_per_segment")
        if pages_per_segment is not None and (
            not isinstance(pages_per_segment, int) or isinstance(pages_per_segment, bool)
        ):
            raise ValueError("pages_per_segment must be an integer")
        plan_id_text, segment_count, strategy = self._segment_plans.ensure_plan(
            organization_id=item.organization_id,
            execution_id=item.execution_id,
            document_version_id=item.subject_id,
            source_checksum_sha256=checksum,
            content_length=handle.content_length,
            execution_class=inspection.execution_class.value,
            detected_media_type=handle.detected_media_type,
            page_count_hint=inspection.page_count_hint,
            pages_per_segment=pages_per_segment,
        )
        plan_id = UUID(plan_id_text)
        segment = self._checkpoints.start_next(plan_id=plan_id)
        if segment is None:
            raise RuntimeError("segment plan has no executable segment")

        execution_item = item
        if strategy == "pdf_page_range":
            segment_options = dict(options)
            segment_options.update(
                {
                    "page_start": int(segment.metadata_["page_start"]),
                    "page_end_exclusive": int(segment.metadata_["page_end_exclusive"]),
                }
            )
            payload = dict(item.input_payload)
            payload["options"] = segment_options
            execution_item = replace(item, input_payload=payload)

        try:
            result = self._delegate.execute(execution_item, heartbeat)
        except Exception:
            self._checkpoints.fail(segment_id=segment.id)
            raise
        else:
            self._checkpoints.complete(segment_id=segment.id)

        summary = self._checkpoints.summary(plan_id=plan_id)
        metrics = dict(result.metrics)
        metrics.update(
            {
                "segment_plan_connected": True,
                "segment_plan_id": plan_id_text,
                "segment_plan_segment_count": segment_count,
                "segment_plan_strategy": strategy,
                "segment_checkpoint_connected": True,
                "segment_checkpoint_total": summary.total_segments,
                "segment_checkpoint_completed": summary.completed_segments,
                "segment_checkpoint_pending": summary.pending_segments,
                "segment_checkpoint_processing": summary.processing_segments,
                "segment_checkpoint_failed": summary.failed_segments,
                "segment_ordinal": segment.ordinal,
                "segment_range_start": segment.range_start,
                "segment_range_end_exclusive": segment.range_end_exclusive,
                "segment_range_unit": segment.metadata_.get("range_unit", "byte"),
                "segment_resume_required": summary.completed_segments < summary.total_segments,
            }
        )
        return RuntimeAdapterResult(
            metrics=metrics,
            continue_execution=summary.completed_segments < summary.total_segments,
        )
