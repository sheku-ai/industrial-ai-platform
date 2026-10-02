from sqlalchemy import select

from app.models.documents import DocumentVersion
from app.services.ingestion_contracts import IngestionContractError
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeAdapterResult


class DocumentVersionStatusService:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def mark_processing(self, organization_id, document_version_id, *, execution_id):
        self._set_status(organization_id, document_version_id, status="processing", execution_id=execution_id)

    def mark_partially_available(self, organization_id, document_version_id, *, execution_id):
        self._set_status(organization_id, document_version_id, status="partially_available", execution_id=execution_id)

    def mark_indexed(self, organization_id, document_version_id, *, execution_id):
        self._set_status(organization_id, document_version_id, status="indexed", execution_id=execution_id)

    def mark_failed(self, organization_id, document_version_id, *, execution_id):
        self._set_status(organization_id, document_version_id, status="failed", execution_id=execution_id)

    def mark_cancelled(self, organization_id, document_version_id, *, execution_id):
        self._set_status(organization_id, document_version_id, status="cancelled", execution_id=execution_id)

    def _set_status(self, organization_id, document_version_id, *, status, execution_id):
        session = self._session_factory()
        try:
            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.id == document_version_id, DocumentVersion.organization_id == organization_id
                )
            )
            if version is None:
                raise IngestionContractError("document version was not found for status update")
            snapshot = dict(version.source_snapshot or {})
            snapshot["last_ingestion_execution_id"] = str(execution_id)
            snapshot["last_ingestion_status"] = status
            version.status = status
            version.source_snapshot = snapshot
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class DocumentIngestionStatusAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, status_service: DocumentVersionStatusService, artifact_publisher=None) -> None:
        self._delegate = delegate
        self._status_service = status_service
        self._artifact_publisher = artifact_publisher

    @staticmethod
    def _checkpoint(heartbeat) -> None:
        checkpoint = getattr(heartbeat, "checkpoint", None)
        if callable(checkpoint):
            checkpoint()
            return
        cancellation = getattr(heartbeat, "raise_if_cancellation_requested", None)
        if callable(cancellation):
            cancellation()
        pulse = getattr(heartbeat, "pulse", None)
        if callable(pulse):
            pulse()

    def execute(self, item, heartbeat):
        self._checkpoint(heartbeat)
        self._status_service.mark_processing(item.organization_id, item.subject_id, execution_id=item.execution_id)
        try:
            result = self._delegate.execute(item, heartbeat)
            if self._artifact_publisher is not None:
                self._checkpoint(heartbeat)
                artifact = self._artifact_publisher.publish(
                    organization_id=item.organization_id,
                    execution_id=item.execution_id,
                    attempt_id=item.attempt_id,
                    document_id=item.input_payload["document_id"],
                    document_version_id=item.subject_id,
                    manifest={
                        "execution_type": item.execution_type,
                        "subject_type": item.subject_type,
                        "attempt_number": item.attempt_number,
                        "metrics": dict(result.metrics),
                    },
                )
                result = RuntimeAdapterResult(
                    metrics={
                        **dict(result.metrics),
                        "artifact_publication_connected": True,
                        "artifact_id": str(artifact.artifact_id),
                        "artifact_storage_uri": artifact.storage_uri,
                        "artifact_checksum_sha256": artifact.checksum_sha256,
                        "artifact_size_bytes": artifact.size_bytes,
                    },
                    continue_execution=result.continue_execution,
                )
            self._checkpoint(heartbeat)
        except RuntimeCancellationRequested:
            self._status_service.mark_cancelled(item.organization_id, item.subject_id, execution_id=item.execution_id)
            raise
        except RuntimeLeaseLost:
            raise
        except Exception:
            self._status_service.mark_failed(item.organization_id, item.subject_id, execution_id=item.execution_id)
            raise

        metrics = dict(result.metrics)
        total = int(metrics.get("segment_checkpoint_total") or 0)
        completed = int(metrics.get("segment_checkpoint_completed") or 0)
        partially_available = total > 0 and completed > 0 and completed < total
        if partially_available:
            self._status_service.mark_partially_available(
                item.organization_id, item.subject_id, execution_id=item.execution_id
            )
            metrics["partial_availability_connected"] = True
            metrics["document_availability"] = "partial"
        else:
            self._status_service.mark_indexed(item.organization_id, item.subject_id, execution_id=item.execution_id)
            metrics["partial_availability_connected"] = True
            metrics["document_availability"] = "complete"
        return RuntimeAdapterResult(metrics=metrics, continue_execution=result.continue_execution)
