from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.services.ingestion_adapters import pdf as pdf_module
from app.services.ingestion_adapters.pdf import PdfIngestionAdapter
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
        adapter_key="platform.pdf.text_layer",
        adapter_version="1.0.0",
        pipeline_profile_revision="test-revision",
        settings=settings,
    )


def source(path: Path, media_type: str = "application/pdf") -> AcquiredSource:
    payload = path.read_bytes()
    return AcquiredSource(
        source_reference="object://source/example.pdf",
        local_path=str(path),
        detected_media_type=media_type,
        content_length=len(payload),
        checksum_sha256=sha256(payload).hexdigest(),
    )


def write_pdf(path: Path, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


class FakePage:
    def __init__(self, text: str | None = None, fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    def extract_text(self) -> str | None:
        if self.fail:
            raise RuntimeError("page extraction failed")
        return self.text


class FakeReader:
    pages_template: list[FakePage] = []
    encrypted = False

    def __init__(self, *_args, **_kwargs) -> None:
        self.pages = list(type(self).pages_template)
        self.is_encrypted = type(self).encrypted


def test_validate_accepts_pdf(tmp_path: Path) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path)
    result = PdfIngestionAdapter().validate(source(path), configuration())
    assert result.accepted is True


def test_validate_rejects_invalid_signature(tmp_path: Path) -> None:
    path = tmp_path / "input.pdf"
    path.write_bytes(b"not-a-pdf")
    result = PdfIngestionAdapter().validate(source(path), configuration())
    assert "invalid_pdf_signature" in {issue.code for issue in result.issues}


def test_validate_rejects_wrong_media_type(tmp_path: Path) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path)
    result = PdfIngestionAdapter().validate(source(path, "application/octet-stream"), configuration())
    assert "unsupported_media_type" in {issue.code for issue in result.issues}


def test_validate_enforces_page_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path, pages=2)
    result = PdfIngestionAdapter().validate(source(path), configuration(max_pages=1))
    assert "page_limit_exceeded" in {issue.code for issue in result.issues}


def test_extract_returns_deterministic_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path, pages=2)
    FakeReader.pages_template = [FakePage("First page\r\n"), FakePage("Second page")]
    FakeReader.encrypted = False
    monkeypatch.setattr(pdf_module, "PdfReader", FakeReader)

    adapter = PdfIngestionAdapter()
    first = adapter.extract(source(path), configuration(), Control())
    second = adapter.extract(source(path), configuration(), Control())

    assert [unit.text for unit in first.content_units] == ["First page", "Second page"]
    assert [unit.unit_key for unit in first.content_units] == [unit.unit_key for unit in second.content_units]
    assert first.metrics["ocr_used"] is False
    assert first.proposed_artifacts == ()


def test_extract_skips_empty_page(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path, pages=2)
    FakeReader.pages_template = [FakePage(""), FakePage("Visible text")]
    monkeypatch.setattr(pdf_module, "PdfReader", FakeReader)

    result = PdfIngestionAdapter().extract(source(path), configuration(), Control())

    assert len(result.content_units) == 1
    assert result.metrics["empty_pages"] == 1
    assert "page_without_text" in {warning.code for warning in result.warnings}


def test_extract_requires_text_layer(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path)
    FakeReader.pages_template = [FakePage("")]
    monkeypatch.setattr(pdf_module, "PdfReader", FakeReader)

    with pytest.raises(IngestionContractError, match="OCR capability is not configured"):
        PdfIngestionAdapter().extract(source(path), configuration(), Control())


def test_extract_checks_cancellation(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "input.pdf"
    write_pdf(path, pages=2)
    FakeReader.pages_template = [FakePage("First"), FakePage("Second")]
    monkeypatch.setattr(pdf_module, "PdfReader", FakeReader)

    with pytest.raises(RuntimeError, match="cancelled"):
        PdfIngestionAdapter().extract(source(path), configuration(), Control(cancel_after=1))


def test_adapter_has_no_ocr_or_persistence_state() -> None:
    adapter = PdfIngestionAdapter()
    assert adapter.capabilities.supports_ocr is False
    assert adapter.capabilities.requires_external_binary is False
    assert not hasattr(adapter, "session")
    assert not hasattr(adapter, "repository")
    assert not hasattr(adapter, "provider")
