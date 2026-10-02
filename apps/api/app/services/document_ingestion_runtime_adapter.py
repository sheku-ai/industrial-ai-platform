from __future__ import annotations

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.services.ingestion_configuration import IngestionConfigurationService
from app.services.ingestion_contracts import (
    AcquiredSource,
    IngestionContractError,
    IngestionExecutionControl,
    IngestionRequest,
)
from app.services.ingestion_pipeline import IngestionPipelineCoordinator, IngestionPipelineInput
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeHeartbeat, RuntimeWorkItem


class SourceAcquisitionService(Protocol):
    def acquire(
        self,
        organization_id: UUID,
        source_reference: str,
        *,
        execution_id: UUID,
        attempt_number: int,
    ) -> AcquiredSource: ...


@dataclass
class HeartbeatIngestionControl(IngestionExecutionControl):
    heartbeat: RuntimeHeartbeat

    def pulse(self) -> None:
        self.heartbeat.pulse()

    def checkpoint(self) -> None:
        checkpoint = getattr(self.heartbeat, "checkpoint", None)
        if checkpoint is not None:
            checkpoint()
            return
        self.raise_if_cancellation_requested()
        self.pulse()

    def is_cancellation_requested(self) -> bool:
        checker = getattr(self.heartbeat, "is_cancellation_requested", None)
        return bool(checker()) if checker is not None else False

    def raise_if_cancellation_requested(self) -> None:
        checker = getattr(self.heartbeat, "raise_if_cancellation_requested", None)
        if checker is not None:
            checker()


class DocumentIngestionRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(
        self,
        acquisition: SourceAcquisitionService,
        configuration: IngestionConfigurationService,
        pipeline: IngestionPipelineCoordinator,
        post_processing: IngestionPostProcessingService,
        processing_revisions=None,
        artifact_publication=None,
    ) -> None:
        self._acquisition = acquisition
        self._configuration = configuration
        self._pipeline = pipeline
        self._post_processing = post_processing
        self._processing_revisions = processing_revisions
        self._artifact_publication = artifact_publication

    def execute(
        self,
        item: RuntimeWorkItem,
        heartbeat: RuntimeHeartbeat,
    ) -> RuntimeAdapterResult:
        if item.execution_type != self.execution_type:
            raise IngestionContractError("unsupported runtime execution type")
        if item.subject_type != "document_version":
            raise IngestionContractError("document ingestion requires document_version subject")

        request = _request_from_item(item)
        profile_id = _required_uuid(item.input_payload, "pipeline_profile_id")
        profile = self._configuration.get_profile(item.organization_id, profile_id)

        control = HeartbeatIngestionControl(heartbeat)
        control.checkpoint()
        source = self._acquisition.acquire(
            item.organization_id,
            request.source_reference,
            execution_id=item.execution_id,
            attempt_number=item.attempt_number,
        )
        control.checkpoint()

        resolution = self._pipeline.resolve_adapter(
            request,
            source,
            profile.deployment_edition,
            profile.adapter_policies,
        )
        resolved = self._configuration.resolve_for_adapter(
            profile,
            resolution.adapter.adapter_key,
        )

        result = self._pipeline.execute(
            IngestionPipelineInput(
                request=request,
                source=source,
                configuration=resolved.adapter_configuration,
                deployment_edition=profile.deployment_edition,
                adapter_policies=profile.adapter_policies,
            ),
            control,
        )

        extraction = result.extraction
        processing_revision_id = None
        manifest_artifact_id = None
        try:
            if self._processing_revisions is not None:
                processing_revision_id = self._processing_revisions.start(
                    organization_id=item.organization_id,
                    document_record_id=request.document_id,
                    document_version_id=request.document_version_id,
                    runtime_execution_id=item.execution_id,
                    runtime_attempt_id=item.attempt_id,
                    pipeline_profile_id=profile_id,
                    pipeline_profile_revision=profile.revision,
                    adapter_key=extraction.adapter_key,
                    adapter_version=extraction.adapter_version,
                    configuration_snapshot=dict(item.policy_snapshot),
                    source_checksum_sha256=request.checksum_sha256,
                )

            control.checkpoint()
            post_processing = self._post_processing.process(
                organization_id=item.organization_id,
                document_id=request.document_id,
                document_version_id=request.document_version_id,
                execution_id=item.execution_id,
                pipeline_profile_revision=profile.revision,
                extraction=extraction,
                language_config=_optional_text(item.input_payload, "language_config") or "simple",
                processing_revision_id=processing_revision_id,
            )
            control.checkpoint()

            if self._artifact_publication is not None:
                manifest_artifact_id = self._artifact_publication.publish(
                    organization_id=item.organization_id,
                    execution_id=item.execution_id,
                    attempt_id=item.attempt_id,
                    document_version_id=request.document_version_id,
                    processing_revision_id=processing_revision_id,
                    adapter_key=extraction.adapter_key,
                    adapter_version=extraction.adapter_version,
                    source_checksum_sha256=request.checksum_sha256,
                    content_unit_count=len(extraction.content_units),
                    chunk_count=len(extraction.content_units),
                )
                control.checkpoint()

            if self._processing_revisions is not None:
                self._processing_revisions.complete(
                    organization_id=item.organization_id,
                    runtime_execution_id=item.execution_id,
                    runtime_attempt_id=item.attempt_id,
                    content_unit_count=len(extraction.content_units),
                    chunk_count=len(extraction.content_units),
                    manifest_artifact_id=manifest_artifact_id,
                )
        except RuntimeCancellationRequested:
            self._finish_revision_safely(item, processing_revision_id, "cancelled")
            raise
        except RuntimeLeaseLost:
            self._finish_revision_safely(item, processing_revision_id, "abandoned")
            raise
        except Exception:
            self._finish_revision_safely(item, processing_revision_id, "failed")
            raise

        persistence = post_processing.persistence
        lexical = post_processing.lexical_index
        metrics = {
            **dict(extraction.metrics or {}),
            "adapter_metrics_propagated": True,
            "adapter_key": extraction.adapter_key,
            "adapter_version": extraction.adapter_version,
            "detected_media_type": extraction.detected_media_type,
            "detected_format": extraction.detected_format,
            "content_units": len(extraction.content_units),
            "warnings": len(extraction.warnings),
            "pipeline_profile_revision": profile.revision,
            "persisted_inserted_units": persistence.inserted_units,
            "persisted_replaced_units": persistence.replaced_units,
            "persisted_unchanged_units": persistence.unchanged_units,
            "lexical_indexed_documents": lexical.indexed_documents,
            "lexical_unchanged_documents": lexical.unchanged_documents,
            "persistence_connected": True,
            "artifact_publication_connected": manifest_artifact_id is not None,
            "lexical_index_connected": True,
            "semantic_publication_connected": False,
            "processing_revision_connected": processing_revision_id is not None,
        }
        if processing_revision_id is not None:
            metrics["processing_revision_id"] = str(processing_revision_id)
        if manifest_artifact_id is not None:
            metrics["manifest_artifact_id"] = str(manifest_artifact_id)
        return RuntimeAdapterResult(metrics=metrics)

    def _finish_revision_safely(self, item, processing_revision_id, status: str) -> None:
        if self._processing_revisions is None or processing_revision_id is None:
            return
        with contextlib.suppress(Exception):
            self._processing_revisions.fail(
                organization_id=item.organization_id,
                runtime_execution_id=item.execution_id,
                runtime_attempt_id=item.attempt_id,
                status=status,
            )


def _request_from_item(item: RuntimeWorkItem) -> IngestionRequest:
    payload = item.input_payload
    document_id = _required_uuid(payload, "document_id")
    document_version_id = _required_uuid(payload, "document_version_id")
    if document_version_id != item.subject_id:
        raise IngestionContractError("runtime subject does not match document version")

    return IngestionRequest(
        organization_id=item.organization_id,
        execution_id=item.execution_id,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        document_id=document_id,
        document_version_id=document_version_id,
        source_reference=_required_text(payload, "source_reference"),
        declared_media_type=_required_text(payload, "declared_media_type"),
        original_file_name=_required_text(payload, "original_file_name"),
        content_length=_optional_int(payload, "content_length"),
        checksum_sha256=_optional_text(payload, "checksum_sha256"),
        pipeline_profile_id=_required_uuid(payload, "pipeline_profile_id"),
        adapter_hint=_optional_text(payload, "adapter_hint"),
        metadata_template_id=_optional_uuid(payload, "metadata_template_id"),
        metadata=_mapping(payload, "metadata"),
        options=_mapping(payload, "options"),
    )


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IngestionContractError(f"{key} is required")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IngestionContractError(f"{key} must be a non-blank string")
    return value.strip()


def _required_uuid(payload: Mapping[str, Any], key: str) -> UUID:
    value = payload.get(key)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise IngestionContractError(f"{key} must be a UUID") from exc


def _optional_uuid(payload: Mapping[str, Any], key: str) -> UUID | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise IngestionContractError(f"{key} must be a UUID") from exc


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IngestionContractError(f"{key} must be a non-negative integer")
    return value


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise IngestionContractError(f"{key} must be an object")
    return dict(value)
