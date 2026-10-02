from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from app.services.embedded_image_visual_pipeline import EmbeddedImageVisualPipeline
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    ProcessingPolicy,
    ProcessingProfile,
    VisualUnderstandingRequest,
)
from app.services.ooxml_embedded_image_extractor import OoxmlEmbeddedImageExtractor
from app.services.pdf_embedded_image_extractor import PdfEmbeddedImageExtractor
from app.services.s3_source_acquisition import S3SourceAcquisitionService
from app.services.visual_understanding import (
    DeterministicLocalVisualProvider,
    VisualUnderstandingCache,
    VisualUnderstandingService,
)
from app.services.visual_understanding_batch import VisualUnderstandingBatchProcessor

logger = logging.getLogger(__name__)


_MEDIA_TYPE_FORMATS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
_SUPPORTED_FORMATS = frozenset({"pdf", "docx", "pptx", "xlsx"})


class RuntimeVisualEnrichmentProducer:
    """Builds an optional visual-enrichment/v1 artifact from the runtime source.

    The producer is provider-neutral at its public boundary. Visual understanding
    remains disabled when no provider is configured, so textual ingestion can run
    independently from AI services.
    """

    def __init__(
        self,
        acquisition: S3SourceAcquisitionService,
        *,
        batch_processor: VisualUnderstandingBatchProcessor | None = None,
        default_profile: ProcessingProfile = ProcessingProfile.BALANCED,
        pdf_extractor: PdfEmbeddedImageExtractor | None = None,
        ooxml_extractor: OoxmlEmbeddedImageExtractor | None = None,
    ) -> None:
        self._acquisition = acquisition
        self._batch_processor = batch_processor
        self._default_profile = default_profile
        self._pdf_extractor = pdf_extractor or PdfEmbeddedImageExtractor()
        self._ooxml_extractor = ooxml_extractor or OoxmlEmbeddedImageExtractor()

    @classmethod
    def from_environment(
        cls,
        acquisition: S3SourceAcquisitionService,
    ) -> RuntimeVisualEnrichmentProducer:
        profile = _processing_profile(os.getenv("VISUAL_UNDERSTANDING_PROFILE", "balanced"))
        provider_key = os.getenv("VISUAL_UNDERSTANDING_PROVIDER", "disabled").strip().lower()
        batch_processor = _batch_processor_from_configuration(provider_key)
        return cls(
            acquisition,
            batch_processor=batch_processor,
            default_profile=profile,
        )

    def produce(self, item, heartbeat) -> Mapping[str, Any] | None:
        source_reference = _required_text(item.input_payload, "source_reference")
        declared_media_type = _optional_text(item.input_payload, "declared_media_type")
        original_file_name = _optional_text(item.input_payload, "original_file_name")
        options = _mapping(item.input_payload, "options")
        policy_snapshot = item.policy_snapshot if isinstance(item.policy_snapshot, dict) else {}

        profile = _resolve_profile(options, policy_snapshot, self._default_profile)
        policy = _resolve_policy(profile, options, policy_snapshot)
        if not policy.enable_visual_understanding:
            logger.info(
                "visual_enrichment_skipped reason=disabled execution_id=%s profile=%s",
                item.execution_id,
                profile.value,
            )
            return None
        if self._batch_processor is None:
            logger.warning(
                "visual_enrichment_skipped reason=provider_unconfigured execution_id=%s profile=%s",
                item.execution_id,
                profile.value,
            )
            return None

        checkpoint = getattr(heartbeat, "checkpoint", None)
        if callable(checkpoint):
            checkpoint()

        handle = self._acquisition.open_handle(source_reference)
        source_format = _resolve_format(
            declared_media_type=declared_media_type,
            detected_media_type=handle.detected_media_type,
            original_file_name=original_file_name,
            source_reference=source_reference,
        )
        if source_format not in _SUPPORTED_FORMATS:
            logger.info(
                "visual_enrichment_skipped reason=unsupported_format execution_id=%s format=%s",
                item.execution_id,
                source_format or "unknown",
            )
            return None
        if handle.content_length > policy.budget.max_source_bytes:
            logger.warning(
                "visual_enrichment_skipped reason=source_budget_exceeded execution_id=%s bytes=%s limit=%s",
                item.execution_id,
                handle.content_length,
                policy.budget.max_source_bytes,
            )
            return None

        payload = b"".join(handle.iter_bytes())
        if callable(checkpoint):
            checkpoint()

        request = VisualUnderstandingRequest(
            profile=profile,
            prompt=_visual_prompt(options, policy_snapshot),
            configuration=_visual_configuration(options, policy_snapshot),
            timeout_seconds=float(min(policy.budget.timeout_seconds, _visual_timeout(options, policy_snapshot))),
        )
        pipeline, extractor_kwargs = self._pipeline_for(source_format)

        try:
            result = pipeline.run(
                payload,
                policy=policy,
                request=request,
                extractor_kwargs=extractor_kwargs,
            )
        except Exception as exc:
            logger.warning(
                "visual_enrichment_degraded execution_id=%s format=%s error=%s: %s",
                item.execution_id,
                source_format,
                type(exc).__name__,
                exc,
            )
            return None

        if callable(checkpoint):
            checkpoint()
        if not result.extraction.occurrences:
            logger.info(
                "visual_enrichment_skipped reason=no_embedded_images execution_id=%s format=%s",
                item.execution_id,
                source_format,
            )
            return None
        if result.artifact is None:
            logger.warning(
                "visual_enrichment_skipped reason=artifact_unavailable execution_id=%s format=%s",
                item.execution_id,
                source_format,
            )
            return None
        return result.artifact

    def _pipeline_for(self, source_format: str):
        if source_format == "pdf":
            return (
                EmbeddedImageVisualPipeline(
                    self._pdf_extractor,
                    batch_processor=self._batch_processor,
                ),
                {},
            )
        return (
            EmbeddedImageVisualPipeline(
                self._ooxml_extractor,
                batch_processor=self._batch_processor,
            ),
            {"source_kind": source_format},
        )


def _batch_processor_from_configuration(provider_key: str) -> VisualUnderstandingBatchProcessor | None:
    if provider_key in {"", "disabled", "none", "off"}:
        return None
    if provider_key in {"deterministic-local", "deterministic_local"}:
        cache_root = os.getenv("VISUAL_UNDERSTANDING_CACHE_ROOT", "").strip()
        cache = VisualUnderstandingCache(cache_root) if cache_root else None
        service = VisualUnderstandingService(
            DeterministicLocalVisualProvider(),
            cache=cache,
        )
        return VisualUnderstandingBatchProcessor(service)
    logger.warning("visual_provider_unrecognized provider_key=%s", provider_key)
    return None


def _resolve_profile(
    options: Mapping[str, Any],
    policy_snapshot: Mapping[str, Any],
    default: ProcessingProfile,
) -> ProcessingProfile:
    value = _nested_value(options, "visual_understanding", "profile")
    if value is None:
        value = _nested_value(policy_snapshot, "visual_understanding", "profile")
    return _processing_profile(value) if value is not None else default


def _resolve_policy(
    profile: ProcessingProfile,
    options: Mapping[str, Any],
    policy_snapshot: Mapping[str, Any],
) -> ProcessingPolicy:
    policy = DEFAULT_PROCESSING_POLICIES[profile]
    enabled = _nested_value(options, "visual_understanding", "enabled")
    if enabled is None:
        enabled = _nested_value(policy_snapshot, "visual_understanding", "enabled")
    if enabled is None:
        enabled = os.getenv("VISUAL_UNDERSTANDING_ENABLED", "0")
    return replace(policy, enable_visual_understanding=_as_bool(enabled))


def _resolve_format(
    *,
    declared_media_type: str | None,
    detected_media_type: str | None,
    original_file_name: str | None,
    source_reference: str,
) -> str | None:
    for media_type in (declared_media_type, detected_media_type):
        normalized = (media_type or "").split(";", 1)[0].strip().lower()
        if normalized in _MEDIA_TYPE_FORMATS:
            return _MEDIA_TYPE_FORMATS[normalized]
    for candidate in (original_file_name, urlparse(source_reference).path):
        suffix = PurePosixPath(candidate or "").suffix.lower().lstrip(".")
        if suffix in _SUPPORTED_FORMATS:
            return suffix
    return None


def _visual_prompt(options: Mapping[str, Any], policy_snapshot: Mapping[str, Any]) -> str:
    value = _nested_value(options, "visual_understanding", "prompt")
    if value is None:
        value = _nested_value(policy_snapshot, "visual_understanding", "prompt")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "Describe the image using observable, provider-neutral facts."


def _visual_configuration(options: Mapping[str, Any], policy_snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _nested_value(options, "visual_understanding", "configuration")
    if value is None:
        value = _nested_value(policy_snapshot, "visual_understanding", "configuration")
    return dict(value) if isinstance(value, dict) else {}


def _visual_timeout(options: Mapping[str, Any], policy_snapshot: Mapping[str, Any]) -> float:
    value = _nested_value(options, "visual_understanding", "timeout_seconds")
    if value is None:
        value = _nested_value(policy_snapshot, "visual_understanding", "timeout_seconds")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(os.getenv("VISUAL_UNDERSTANDING_TIMEOUT_SECONDS", "30"))
    return max(parsed, 0.001)


def _processing_profile(value: Any) -> ProcessingProfile:
    try:
        return ProcessingProfile(str(value).strip().lower())
    except ValueError:
        logger.warning("visual_profile_invalid value=%s fallback=balanced", value)
        return ProcessingProfile.BALANCED


def _nested_value(source: Mapping[str, Any], section: str, key: str) -> Any:
    nested = source.get(section)
    return nested.get(key) if isinstance(nested, dict) else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}
