from __future__ import annotations

from time import perf_counter

from app.services.multimodal_observability import visual_artifact_metrics
from app.services.runtime_worker import RuntimeAdapterResult


class VisualEnrichmentRuntimeAdapter:
    """Produces and publishes optional visual evidence before knowledge generation."""

    execution_type = "document.ingestion"

    def __init__(self, delegate, producer, publisher) -> None:
        self._delegate = delegate
        self._producer = producer
        self._publisher = publisher

    def execute(self, item, heartbeat):
        result = self._delegate.execute(item, heartbeat)
        metrics = dict(result.metrics)
        started_at = perf_counter()

        checkpoint = getattr(heartbeat, "checkpoint", None)
        if callable(checkpoint):
            checkpoint()

        try:
            visual_artifact = self._producer.produce(item, heartbeat)
        except Exception as error:
            return self._degraded_result(result, metrics, error, started_at)

        if visual_artifact is None:
            metrics.update(
                visual_enrichment_connected=True,
                visual_enrichment_published=False,
                visual_enrichment_degraded=False,
                visual_enrichment_duration_ms=_elapsed_ms(started_at),
                visual_items_detected=0,
                visual_items_enriched=0,
                visual_items_skipped=0,
                visual_items_failed=0,
                visual_items_partial=0,
                visual_provider_counts={},
                visual_status_counts={},
                multimodal_flow_status="not_applicable",
                multimodal_processing_revision_id=metrics.get("processing_revision_id"),
            )
            return RuntimeAdapterResult(
                metrics=metrics,
                continue_execution=result.continue_execution,
            )

        metrics.update(visual_artifact_metrics(visual_artifact))
        try:
            artifact_id = self._publisher.publish(
                organization_id=item.organization_id,
                execution_id=item.execution_id,
                attempt_id=item.attempt_id,
                document_version_id=item.subject_id,
                processing_revision_id=metrics.get("processing_revision_id"),
                artifact=visual_artifact,
            )
        except Exception as error:
            return self._degraded_result(result, metrics, error, started_at)

        metrics.update(
            visual_enrichment_connected=True,
            visual_enrichment_published=True,
            visual_enrichment_degraded=False,
            visual_enrichment_artifact_id=str(artifact_id),
            visual_enrichment_duration_ms=_elapsed_ms(started_at),
            multimodal_processing_revision_id=metrics.get("processing_revision_id"),
        )
        if callable(checkpoint):
            checkpoint()
        return RuntimeAdapterResult(
            metrics=metrics,
            continue_execution=result.continue_execution,
        )

    @staticmethod
    def _degraded_result(result, metrics, error, started_at):
        metrics.update(
            visual_enrichment_connected=True,
            visual_enrichment_published=False,
            visual_enrichment_degraded=True,
            visual_enrichment_error_type=type(error).__name__,
            visual_enrichment_duration_ms=_elapsed_ms(started_at),
            multimodal_flow_status="degraded",
            multimodal_processing_revision_id=metrics.get("processing_revision_id"),
        )
        return RuntimeAdapterResult(
            metrics=metrics,
            continue_execution=result.continue_execution,
        )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
