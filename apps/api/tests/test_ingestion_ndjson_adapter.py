from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from app.services.ingestion_adapters.ndjson import NdjsonIngestionAdapter
from app.services.ingestion_contracts import AcquiredSource, IngestionContractError, ResolvedAdapterConfiguration


class Control:
    def __init__(self, cancel_after: int | None = None) -> None:
        self.pulses = 0
        self.cancel_after = cancel_after

    def pulse(self) -> None:
        self.pulses += 1

    def is_cancellation_requested(self) -> bool:
        return self.cancel_after is not None and self.pulses >= self.cancel_after

    def raise_if_cancellation_requested(self) -> None:
        if self.is_cancellation_requested():
            raise RuntimeError("cancelled")


def configuration(**settings) -> ResolvedAdapterConfiguration:
    return ResolvedAdapterConfiguration(
        adapter_key="platform.ndjson.generic",
        adapter_version="1.0.0",
        pipeline_profile_revision="test-revision",
        settings=settings,
    )


def source(path: Path, media_type: str = "application/x-ndjson") -> AcquiredSource:
    payload = path.read_bytes()
    return AcquiredSource(
        source_reference="object://source/data.ndjson",
        local_path=str(path),
        detected_media_type=media_type,
        content_length=len(payload),
        checksum_sha256=sha256(payload).hexdigest(),
    )


def test_validate_accepts_object_records(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"name":"alpha"}\n{"name":"beta"}\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().validate(source(path), configuration())

    assert result.accepted is True
    assert result.issues == ()


def test_validate_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"name":"alpha"}\nnot-json\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().validate(source(path), configuration())

    assert "invalid_json_record" in {issue.code for issue in result.issues}


def test_validate_rejects_scalar_record(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('42\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().validate(source(path), configuration())

    assert "record_must_be_object" in {issue.code for issue in result.issues}


def test_validate_rejects_blank_line_when_disabled(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"name":"alpha"}\n\n{"name":"beta"}\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().validate(
        source(path), configuration(allow_blank_lines=False)
    )

    assert "blank_line_not_allowed" in {issue.code for issue in result.issues}


def test_extract_returns_deterministic_structured_objects(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text(
        '{"value":1,"name":"alpha"}\n{"name":"beta","value":2}\n',
        encoding="utf-8",
    )
    adapter = NdjsonIngestionAdapter()

    first = adapter.extract(source(path), configuration(), Control())
    second = adapter.extract(source(path), configuration(), Control())

    assert [unit.structured_data for unit in first.content_units] == [
        {"value": 1, "name": "alpha"},
        {"name": "beta", "value": 2},
    ]
    assert [unit.unit_key for unit in first.content_units] == [
        unit.unit_key for unit in second.content_units
    ]
    assert first.content_units[0].source_locator == {"line_number": 1}
    assert first.metrics["embeddings_generated"] is False
    assert first.metrics["vectors_published"] is False


def test_extract_skips_blank_lines_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"name":"alpha"}\n\n{"name":"beta"}\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().extract(source(path), configuration(), Control())

    assert len(result.content_units) == 2
    assert result.metrics["blank_lines"] == 1
    assert "blank_lines_skipped" in {warning.code for warning in result.warnings}


def test_validate_enforces_record_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")

    result = NdjsonIngestionAdapter().validate(
        source(path), configuration(max_records=1)
    )

    assert "record_limit_exceeded" in {issue.code for issue in result.issues}


def test_extract_enforces_key_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"a":1,"b":2}\n', encoding="utf-8")

    with pytest.raises(IngestionContractError, match="key limit"):
        NdjsonIngestionAdapter().extract(
            source(path), configuration(max_keys_per_record=1), Control()
        )


def test_extract_enforces_depth_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"a":{"b":{"c":1}}}\n', encoding="utf-8")

    with pytest.raises(IngestionContractError, match="object depth"):
        NdjsonIngestionAdapter().extract(
            source(path), configuration(max_object_depth=2), Control()
        )


def test_extract_checks_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "input.ndjson"
    path.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="cancelled"):
        NdjsonIngestionAdapter().extract(
            source(path), configuration(), Control(cancel_after=1)
        )


def test_adapter_has_no_embedding_vector_or_persistence_state() -> None:
    adapter = NdjsonIngestionAdapter()

    assert adapter.capabilities.supports_structured_output is True
    assert adapter.capabilities.requires_external_binary is False
    assert not hasattr(adapter, "session")
    assert not hasattr(adapter, "repository")
    assert not hasattr(adapter, "embedding_model")
    assert not hasattr(adapter, "vector_store")
