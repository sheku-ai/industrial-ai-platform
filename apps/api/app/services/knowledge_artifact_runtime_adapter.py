from __future__ import annotations

from time import perf_counter
from uuid import UUID

from app.services.runtime_worker import RuntimeAdapterResult, RuntimeHeartbeat, RuntimeWorkItem


class KnowledgeArtifactRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, publication_service, visual_chunk_indexing_service=None) -> None:
        if getattr(delegate, "execution_type", None) != self.execution_type:
            raise ValueError("delegate must implement document.ingestion")
        self._delegate = delegate
        self._publication_service = publication_service
        self._visual_chunk_indexing_service = visual_chunk_indexing_service

    def execute(self, item: RuntimeWorkItem, heartbeat: RuntimeHeartbeat) -> RuntimeAdapterResult:
        result = self._delegate.execute(item, heartbeat)
        if result.continue_execution:
            return result
        document_version_id = _required_uuid(item.input_payload.get("document_version_id"), "document_version_id")
        processing_revision_id = _optional_uuid(result.metrics.get("processing_revision_id"))
        heartbeat.pulse()
        artifact_id = self._publication_service.publish(
            organization_id=item.organization_id,
            execution_id=item.execution_id,
            attempt_id=item.attempt_id,
            document_version_id=document_version_id,
            processing_revision_id=processing_revision_id,
        )
        heartbeat.pulse()
        metrics = {
            "visual_chunk_indexing_connected": False,
            "visual_chunk_indexing_failed": False,
            "visual_chunks_created": 0,
            "visual_chunks_existing": 0,
            "visual_chunks_requested": 0,
            "visual_text_chunks_available": 0,
            "visual_chunk_indexing_duration_ms": 0,
            "visual_chunk_provider_counts": {},
            "visual_chunk_status_counts": {},
            "multimodal_processing_revision_id": (str(processing_revision_id) if processing_revision_id else None),
        }
        if self._visual_chunk_indexing_service is not None:
            indexing_started_at = perf_counter()
            try:
                metrics = self._visual_chunk_indexing_service.run(
                    organization_id=item.organization_id,
                    execution_id=item.execution_id,
                    document_version_id=document_version_id,
                    processing_revision_id=processing_revision_id,
                )
            except Exception as error:
                metrics = {
                    **metrics,
                    "visual_chunk_indexing_connected": True,
                    "visual_chunk_indexing_failed": True,
                    "visual_chunk_indexing_error_type": type(error).__name__,
                    "visual_chunk_indexing_duration_ms": _elapsed_ms(indexing_started_at),
                    "multimodal_flow_status": "degraded",
                }
        heartbeat.pulse()
        return RuntimeAdapterResult(
            metrics={
                **dict(result.metrics),
                "knowledge_artifact_publication_connected": True,
                "knowledge_artifact_id": str(artifact_id),
                **metrics,
            },
            continue_execution=False,
        )


def _required_uuid(value, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _optional_uuid(value) -> UUID | None:
    if value in {None, ""}:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("processing_revision_id must be a UUID") from exc


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
