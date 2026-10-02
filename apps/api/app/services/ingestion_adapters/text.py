from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from app.services.ingestion_contracts import (
    AcquiredSource,
    AdapterCapabilities,
    ContentUnit,
    ExtractionResult,
    ExtractionWarning,
    IngestionContractError,
    IngestionExecutionControl,
    IngestionUnitType,
    ResolvedAdapterConfiguration,
    ValidationIssue,
    ValidationResult,
)


class PlainTextIngestionAdapter:
    """Deterministic adapter for plain-text and Markdown content.

    The adapter reads only the acquired workspace file, validates its content,
    normalizes line endings and returns content units. It does not persist data,
    publish artifacts, access runtime state or invoke AI components.
    """

    adapter_key = "platform.text.plain"
    adapter_version = "1.0.0"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"text/plain", "text/markdown"}),
        priority=100,
        requires_external_binary=False,
        supports_ocr=False,
        supports_structured_output=False,
        supports_cancellation=True,
        community_available=True,
        enterprise_available=True,
    )

    def validate(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
    ) -> ValidationResult:
        del configuration

        issues: list[ValidationIssue] = []
        path = Path(source.local_path)

        if source.detected_media_type not in self.capabilities.supported_media_types:
            issues.append(
                ValidationIssue(
                    code="unsupported_media_type",
                    message="detected media type is not supported by the plain-text adapter",
                )
            )

        if not path.is_file():
            issues.append(
                ValidationIssue(
                    code="source_not_found",
                    message="acquired source file is not available",
                    retryable=False,
                )
            )
        else:
            stat_size = path.stat().st_size
            if stat_size != source.content_length:
                issues.append(
                    ValidationIssue(
                        code="content_length_mismatch",
                        message="acquired source length does not match the registered source",
                    )
                )

            digest = _sha256_file(path)
            if digest != source.checksum_sha256:
                issues.append(
                    ValidationIssue(
                        code="checksum_mismatch",
                        message="acquired source checksum does not match the registered source",
                    )
                )

            if stat_size == 0:
                issues.append(
                    ValidationIssue(
                        code="empty_content",
                        message="plain-text source is empty",
                    )
                )
            elif _contains_nul_byte(path):
                issues.append(
                    ValidationIssue(
                        code="binary_content_detected",
                        message="plain-text source contains binary content markers",
                    )
                )

        return ValidationResult(
            accepted=not issues,
            detected_media_type=source.detected_media_type,
            issues=tuple(issues),
        )

    def extract(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
        control: IngestionExecutionControl,
    ) -> ExtractionResult:
        validation = self.validate(source, configuration)
        if not validation.accepted:
            raise IngestionContractError("source failed plain-text adapter validation")

        control.raise_if_cancellation_requested()
        control.pulse()

        path = Path(source.local_path)
        raw = path.read_bytes()
        text, encoding, warnings = _decode_text(raw, configuration.settings)
        normalized = _normalize_text(text)

        if not normalized:
            raise IngestionContractError("normalized plain-text content is empty")

        split_on_blank_lines = _setting_bool(
            configuration.settings,
            "split_on_blank_lines",
            default=True,
        )
        max_units = _setting_positive_int(
            configuration.settings,
            "max_units",
            default=10_000,
        )

        sections = _split_sections(normalized, split_on_blank_lines=split_on_blank_lines)
        if len(sections) > max_units:
            raise IngestionContractError("plain-text source exceeds configured content unit limit")

        units: list[ContentUnit] = []
        offset = 0
        for ordinal, section in enumerate(sections):
            control.raise_if_cancellation_requested()

            start = normalized.find(section, offset)
            if start < 0:
                start = offset
            end = start + len(section)
            offset = end

            content_hash = sha256(section.encode("utf-8")).hexdigest()
            units.append(
                ContentUnit(
                    unit_key=f"text:{ordinal}:{content_hash[:16]}",
                    ordinal=ordinal,
                    unit_type=IngestionUnitType.TEXT_SECTION,
                    content_hash=content_hash,
                    text=section,
                    source_locator={
                        "character_start": start,
                        "character_end": end,
                    },
                    attributes={
                        "encoding": encoding,
                    },
                )
            )
            control.pulse()

        return ExtractionResult(
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            detected_media_type=source.detected_media_type,
            detected_format="plain_text",
            content_units=tuple(units),
            metrics={
                "source_bytes": len(raw),
                "normalized_characters": len(normalized),
                "content_units": len(units),
                "encoding": encoding,
            },
            warnings=tuple(warnings),
            quality_observations=(),
        )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _contains_nul_byte(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\x00" in handle.read(8192)


def _decode_text(
    raw: bytes,
    settings: dict[str, Any] | Any,
) -> tuple[str, str, list[ExtractionWarning]]:
    configured_encoding = str(settings.get("encoding", "utf-8")).strip().lower()
    allow_replacement = _setting_bool(settings, "allow_replacement_characters", default=False)

    candidate_encodings = _deduplicate((configured_encoding, "utf-8-sig", "utf-8"))
    decode_errors: list[UnicodeDecodeError] = []

    for encoding in candidate_encodings:
        try:
            return raw.decode(encoding), encoding, []
        except UnicodeDecodeError as exc:
            decode_errors.append(exc)

    if allow_replacement:
        text = raw.decode(configured_encoding, errors="replace")
        return (
            text,
            configured_encoding,
            [
                ExtractionWarning(
                    code="replacement_characters_used",
                    message="source contained invalid byte sequences and was decoded with replacement characters",
                )
            ],
        )

    raise IngestionContractError("plain-text source cannot be decoded with the configured encoding") from decode_errors[
        -1
    ]


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip()


def _split_sections(value: str, *, split_on_blank_lines: bool) -> tuple[str, ...]:
    if not split_on_blank_lines:
        return (value,)

    sections: list[str] = []
    current: list[str] = []

    for line in value.split("\n"):
        if line.strip():
            current.append(line)
            continue

        if current:
            sections.append("\n".join(current).strip())
            current = []

    if current:
        sections.append("\n".join(current).strip())

    return tuple(section for section in sections if section)


def _setting_bool(settings: Any, key: str, *, default: bool) -> bool:
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise IngestionContractError(f"{key} must be a boolean")
    return value


def _setting_positive_int(settings: Any, key: str, *, default: int) -> int:
    value = settings.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IngestionContractError(f"{key} must be a positive integer")
    return value


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
