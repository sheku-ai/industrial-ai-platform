from __future__ import annotations

from dataclasses import dataclass

from app.services.ingestion_adapter_resolver import (
    AdapterPolicy,
    AdapterResolutionRequest,
    AdapterResolutionResult,
    DeploymentEdition,
    IngestionAdapterResolver,
)
from app.services.ingestion_contracts import (
    AcquiredSource,
    ExtractionResult,
    IngestionContractError,
    IngestionExecutionControl,
    IngestionRequest,
    ResolvedAdapterConfiguration,
    ValidationResult,
)


@dataclass(frozen=True)
class IngestionPipelineInput:
    request: IngestionRequest
    source: AcquiredSource
    configuration: ResolvedAdapterConfiguration
    deployment_edition: DeploymentEdition
    adapter_policies: tuple[AdapterPolicy, ...] = ()


@dataclass(frozen=True)
class IngestionPipelineResult:
    resolution: AdapterResolutionResult
    validation: ValidationResult
    extraction: ExtractionResult


class IngestionPipelineCoordinator:
    """Coordinate resolution, validation and extraction without persistence."""

    def __init__(self, resolver: IngestionAdapterResolver) -> None:
        self._resolver = resolver

    def resolve_adapter(
        self,
        request: IngestionRequest,
        source: AcquiredSource,
        deployment_edition: DeploymentEdition,
        adapter_policies: tuple[AdapterPolicy, ...] = (),
    ) -> AdapterResolutionResult:
        self._validate_source_identity(request, source)
        return self._resolver.resolve(
            AdapterResolutionRequest(
                declared_media_type=request.declared_media_type,
                detected_media_type=source.detected_media_type,
                deployment_edition=deployment_edition,
                adapter_hint=request.adapter_hint,
            ),
            adapter_policies,
        )

    def execute(
        self,
        pipeline_input: IngestionPipelineInput,
        control: IngestionExecutionControl,
    ) -> IngestionPipelineResult:
        control.raise_if_cancellation_requested()
        control.pulse()

        request = pipeline_input.request
        source = pipeline_input.source
        configuration = pipeline_input.configuration

        resolution = self.resolve_adapter(
            request,
            source,
            pipeline_input.deployment_edition,
            pipeline_input.adapter_policies,
        )

        if configuration.adapter_key != resolution.adapter.adapter_key:
            raise IngestionContractError("configuration adapter mismatch")

        validation = resolution.adapter.validate(source, configuration)
        if not validation.accepted:
            codes = ",".join(issue.code for issue in validation.issues)
            raise IngestionContractError(f"adapter validation failed: {codes}")

        control.raise_if_cancellation_requested()
        extraction = resolution.adapter.extract(source, configuration, control)

        if extraction.adapter_key != resolution.adapter.adapter_key:
            raise IngestionContractError("extraction adapter mismatch")
        if extraction.adapter_version != configuration.adapter_version:
            raise IngestionContractError("extraction adapter version mismatch")
        if extraction.detected_media_type != validation.detected_media_type:
            raise IngestionContractError("extraction media type mismatch")

        control.pulse()
        return IngestionPipelineResult(resolution, validation, extraction)

    @staticmethod
    def _validate_source_identity(
        request: IngestionRequest,
        source: AcquiredSource,
    ) -> None:
        if request.source_reference != source.source_reference:
            raise IngestionContractError("source reference mismatch")
        if request.content_length is not None and request.content_length != source.content_length:
            raise IngestionContractError("source length mismatch")
        if request.checksum_sha256 is not None and request.checksum_sha256 != source.checksum_sha256:
            raise IngestionContractError("source checksum mismatch")
