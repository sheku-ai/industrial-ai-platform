from __future__ import annotations

import json
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


class NdjsonIngestionAdapter:
    """Generic newline-delimited JSON object extractor.

    Each non-empty line must contain one JSON object. The adapter validates and
    returns structured objects only. It does not embed content, write vectors,
    persist chunks, register jobs or reinterpret legacy metadata fields.
    """

    adapter_key = "platform.ndjson.generic"
    adapter_version = "1.0.0"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset(
            {
                "application/x-ndjson",
                "application/ndjson",
                "application/jsonl",
            }
        ),
        priority=100,
        requires_external_binary=False,
        supports_ocr=False,
        supports_structured_output=True,
        supports_cancellation=True,
        community_available=True,
        enterprise_available=True,
    )

    def validate(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        path = Path(source.local_path)

        if source.detected_media_type not in self.capabilities.supported_media_types:
            issues.append(
                ValidationIssue(
                    code="unsupported_media_type",
                    message="detected media type is not supported by the NDJSON adapter",
                )
            )

        if not path.is_file():
            issues.append(
                ValidationIssue(
                    code="source_not_found",
                    message="acquired source file is not available",
                )
            )
            return ValidationResult(False, source.detected_media_type, tuple(issues))

        stat_size = path.stat().st_size
        if stat_size != source.content_length:
            issues.append(
                ValidationIssue(
                    code="content_length_mismatch",
                    message="acquired source length does not match the registered source",
                )
            )

        if _sha256_file(path) != source.checksum_sha256:
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
                    message="NDJSON source is empty",
                )
            )

        encoding = _encoding(configuration.settings)
        max_records = _positive_int(configuration.settings, "max_records", 1_000_000)
        allow_blank_lines = _bool_setting(configuration.settings, "allow_blank_lines", True)

        if not issues:
            record_count = 0
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    for line_number, raw_line in enumerate(handle, start=1):
                        line = raw_line.strip()
                        if not line:
                            if allow_blank_lines:
                                continue
                            issues.append(
                                ValidationIssue(
                                    code="blank_line_not_allowed",
                                    message=f"blank line found at line {line_number}",
                                )
                            )
                            break

                        record_count += 1
                        if record_count > max_records:
                            issues.append(
                                ValidationIssue(
                                    code="record_limit_exceeded",
                                    message="NDJSON source exceeds configured record limit",
                                )
                            )
                            break

                        try:
                            value = json.loads(line)
                        except json.JSONDecodeError:
                            issues.append(
                                ValidationIssue(
                                    code="invalid_json_record",
                                    message=f"invalid JSON object at line {line_number}",
                                )
                            )
                            break

                        if not isinstance(value, dict):
                            issues.append(
                                ValidationIssue(
                                    code="record_must_be_object",
                                    message=f"JSON value at line {line_number} must be an object",
                                )
                            )
                            break
            except (OSError, UnicodeDecodeError):
                issues.append(
                    ValidationIssue(
                        code="invalid_ndjson",
                        message="source cannot be read as configured NDJSON content",
                    )
                )

            if not issues and record_count == 0:
                issues.append(
                    ValidationIssue(
                        code="no_records",
                        message="NDJSON source contains no records",
                    )
                )

        return ValidationResult(not issues, source.detected_media_type, tuple(issues))

    def extract(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
        control: IngestionExecutionControl,
    ) -> ExtractionResult:
        validation = self.validate(source, configuration)
        if not validation.accepted:
            raise IngestionContractError("source failed NDJSON adapter validation")

        control.raise_if_cancellation_requested()
        control.pulse()

        encoding = _encoding(configuration.settings)
        allow_blank_lines = _bool_setting(configuration.settings, "allow_blank_lines", True)
        max_object_depth = _positive_int(configuration.settings, "max_object_depth", 64)
        max_keys_per_record = _positive_int(configuration.settings, "max_keys_per_record", 10_000)

        units: list[ContentUnit] = []
        warnings: list[ExtractionWarning] = []
        blank_lines = 0

        with Path(source.local_path).open("r", encoding=encoding, newline="") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                control.raise_if_cancellation_requested()
                line = raw_line.strip()

                if not line:
                    blank_lines += 1
                    if allow_blank_lines:
                        continue
                    raise IngestionContractError("blank line encountered during NDJSON extraction")

                value = json.loads(line)
                if not isinstance(value, dict):
                    raise IngestionContractError("NDJSON record must be a JSON object")
                if len(value) > max_keys_per_record:
                    raise IngestionContractError("NDJSON record exceeds configured key limit")
                if _object_depth(value) > max_object_depth:
                    raise IngestionContractError("NDJSON record exceeds configured object depth")

                canonical = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                content_hash = sha256(canonical.encode("utf-8")).hexdigest()

                units.append(
                    ContentUnit(
                        unit_key=f"record:{line_number}:{content_hash[:16]}",
                        ordinal=len(units),
                        unit_type=IngestionUnitType.STRUCTURED_OBJECT,
                        content_hash=content_hash,
                        structured_data=value,
                        source_locator={"line_number": line_number},
                        attributes={
                            "top_level_key_count": len(value),
                            "encoding": encoding,
                        },
                    )
                )
                control.pulse()

        if blank_lines:
            warnings.append(
                ExtractionWarning(
                    code="blank_lines_skipped",
                    message=f"{blank_lines} blank lines were skipped",
                )
            )

        return ExtractionResult(
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            detected_media_type=source.detected_media_type,
            detected_format="ndjson",
            content_units=tuple(units),
            proposed_artifacts=(),
            metrics={
                "source_bytes": source.content_length,
                "records": len(units),
                "blank_lines": blank_lines,
                "encoding": encoding,
                "embeddings_generated": False,
                "vectors_published": False,
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


def _encoding(settings: Any) -> str:
    value = str(settings.get("encoding", "utf-8-sig")).strip().lower()
    if not value:
        raise IngestionContractError("encoding is required")
    return value


def _positive_int(settings: Any, key: str, default: int) -> int:
    value = settings.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IngestionContractError(f"{key} must be a positive integer")
    return value


def _bool_setting(settings: Any, key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise IngestionContractError(f"{key} must be a boolean")
    return value


def _object_depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_object_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_object_depth(item) for item in value), default=0)
    return 0
