from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_contracts import (
    AcquiredSource,
    IngestionContractError,
    ResolvedAdapterConfiguration,
)


class Control:
    def __init__(self, *, cancel_after_pulses: int | None = None) -> None:
        self.pulses = 0
        self.cancel_after_pulses = cancel_after_pulses

    def pulse(self) -> None:
        self.pulses += 1

    def is_cancellation_requested(self) -> bool:
        return self.cancel_after_pulses is not None and self.pulses >= self.cancel_after_pulses

    def raise_if_cancellation_requested(self) -> None:
        if self.is_cancellation_requested():
            raise CancelledError("cancelled")


class CancelledError(RuntimeError):
    pass


def _source(path: Path, *, media_type: str = "text/plain") -> AcquiredSource:
    payload = path.read_bytes()
    return AcquiredSource(
        source_reference="object://source/example",
        local_path=str(path),
        detected_media_type=media_type,
        content_length=len(payload),
        checksum_sha256=sha256(payload).hexdigest(),
    )


def _configuration(**settings) -> ResolvedAdapterConfiguration:
    return ResolvedAdapterConfiguration(
        adapter_key="platform.text.plain",
        adapter_version="1.0.0",
        pipeline_profile_revision="test-revision",
        settings=settings,
    )


def test_validate_accepts_matching_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("first section\n\nsecond section", encoding="utf-8")

    result = PlainTextIngestionAdapter().validate(_source(path), _configuration())

    assert result.accepted is True
    assert result.issues == ()


def test_validate_rejects_unsupported_media_type(tmp_path: Path) -> None:
    path = tmp_path / "input.bin"
    path.write_text("content", encoding="utf-8")

    result = PlainTextIngestionAdapter().validate(
        _source(path, media_type="application/octet-stream"),
        _configuration(),
    )

    assert result.accepted is False
    assert [issue.code for issue in result.issues] == ["unsupported_media_type"]


def test_validate_rejects_checksum_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("content", encoding="utf-8")
    source = _source(path)
    path.write_text("changed content", encoding="utf-8")

    result = PlainTextIngestionAdapter().validate(source, _configuration())

    assert result.accepted is False
    assert {issue.code for issue in result.issues} == {
        "content_length_mismatch",
        "checksum_mismatch",
    }


def test_validate_rejects_binary_markers(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_bytes(b"text\x00binary")

    result = PlainTextIngestionAdapter().validate(_source(path), _configuration())

    assert result.accepted is False
    assert "binary_content_detected" in {issue.code for issue in result.issues}


def test_extract_normalizes_and_splits_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_bytes(b"first line  \r\nsecond line\r\n\r\nthird line\r\n")
    adapter = PlainTextIngestionAdapter()

    first = adapter.extract(_source(path), _configuration(), Control())
    second = adapter.extract(_source(path), _configuration(), Control())

    assert [unit.text for unit in first.content_units] == [
        "first line\nsecond line",
        "third line",
    ]
    assert [unit.unit_key for unit in first.content_units] == [
        unit.unit_key for unit in second.content_units
    ]
    assert [unit.content_hash for unit in first.content_units] == [
        unit.content_hash for unit in second.content_units
    ]
    assert first.proposed_artifacts == ()
    assert first.metrics["content_units"] == 2


def test_extract_can_keep_one_content_unit(tmp_path: Path) -> None:
    path = tmp_path / "input.md"
    path.write_text("# Heading\n\nParagraph", encoding="utf-8")

    result = PlainTextIngestionAdapter().extract(
        _source(path, media_type="text/markdown"),
        _configuration(split_on_blank_lines=False),
        Control(),
    )

    assert len(result.content_units) == 1
    assert result.content_units[0].text == "# Heading\n\nParagraph"


def test_extract_rejects_invalid_encoding_without_fallback(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_bytes("olá".encode("latin-1"))

    with pytest.raises(IngestionContractError, match="cannot be decoded"):
        PlainTextIngestionAdapter().extract(
            _source(path),
            _configuration(encoding="utf-8"),
            Control(),
        )


def test_extract_can_use_configured_encoding(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_bytes("olá".encode("latin-1"))

    result = PlainTextIngestionAdapter().extract(
        _source(path),
        _configuration(encoding="latin-1"),
        Control(),
    )

    assert result.content_units[0].text == "olá"
    assert result.metrics["encoding"] == "latin-1"


def test_extract_checks_cooperative_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("first\n\nsecond", encoding="utf-8")

    with pytest.raises(CancelledError):
        PlainTextIngestionAdapter().extract(
            _source(path),
            _configuration(),
            Control(cancel_after_pulses=1),
        )


def test_extract_enforces_content_unit_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("first\n\nsecond", encoding="utf-8")

    with pytest.raises(IngestionContractError, match="content unit limit"):
        PlainTextIngestionAdapter().extract(
            _source(path),
            _configuration(max_units=1),
            Control(),
        )


def test_adapter_has_no_provider_or_persistence_configuration() -> None:
    adapter = PlainTextIngestionAdapter()

    assert adapter.capabilities.requires_external_binary is False
    assert adapter.capabilities.supports_ocr is False
    assert not hasattr(adapter, "session")
    assert not hasattr(adapter, "repository")
    assert not hasattr(adapter, "provider")
