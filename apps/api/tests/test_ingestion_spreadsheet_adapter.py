from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.ingestion_adapters.spreadsheet import SpreadsheetIngestionAdapter
from app.services.ingestion_contracts import AcquiredSource, IngestionContractError, ResolvedAdapterConfiguration

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        adapter_key="platform.spreadsheet.generic",
        adapter_version="1.0.0",
        pipeline_profile_revision="test-revision",
        settings=settings,
    )


def source(path: Path, media_type: str) -> AcquiredSource:
    payload = path.read_bytes()
    return AcquiredSource(
        source_reference="object://source/spreadsheet",
        local_path=str(path),
        detected_media_type=media_type,
        content_length=len(payload),
        checksum_sha256=sha256(payload).hexdigest(),
    )


def write_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Name", "Value", "Value"])
    sheet.append(["Alpha", 10, 20])
    sheet.append(["Beta", 30, 40])
    workbook.save(path)
    workbook.close()


def test_validate_accepts_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_xlsx(path)
    result = SpreadsheetIngestionAdapter().validate(source(path, XLSX_MEDIA_TYPE), configuration())
    assert result.accepted is True


def test_validate_accepts_csv(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Name,Value\nAlpha,10\n", encoding="utf-8")
    result = SpreadsheetIngestionAdapter().validate(source(path, "text/csv"), configuration())
    assert result.accepted is True


def test_validate_rejects_wrong_media_type(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Name,Value\nAlpha,10\n", encoding="utf-8")
    result = SpreadsheetIngestionAdapter().validate(
        source(path, "application/octet-stream"), configuration()
    )
    assert "unsupported_media_type" in {issue.code for issue in result.issues}


def test_extract_xlsx_returns_structured_rows(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_xlsx(path)

    result = SpreadsheetIngestionAdapter().extract(
        source(path, XLSX_MEDIA_TYPE), configuration(), Control()
    )

    assert result.detected_format == "xlsx"
    assert len(result.content_units) == 2
    assert result.content_units[0].structured_data == {
        "Name": "Alpha",
        "Value": 10,
        "Value_2": 20,
    }
    assert result.content_units[0].source_locator == {
        "sheet_name": "Data",
        "row_number": 2,
    }
    assert result.metrics["formulas_evaluated"] is False


def test_extract_csv_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Name;Value\nAlpha;10\nBeta;20\n", encoding="utf-8")
    adapter = SpreadsheetIngestionAdapter()

    first = adapter.extract(
        source(path, "text/csv"), configuration(delimiter=";"), Control()
    )
    second = adapter.extract(
        source(path, "text/csv"), configuration(delimiter=";"), Control()
    )

    assert [unit.unit_key for unit in first.content_units] == [
        unit.unit_key for unit in second.content_units
    ]
    assert [unit.content_hash for unit in first.content_units] == [
        unit.content_hash for unit in second.content_units
    ]


def test_extract_enforces_row_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Name,Value\nAlpha,10\nBeta,20\n", encoding="utf-8")

    with pytest.raises(IngestionContractError, match="row limit"):
        SpreadsheetIngestionAdapter().extract(
            source(path, "text/csv"), configuration(max_rows=1), Control()
        )


def test_extract_supports_configured_header_row(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Report title\nName,Value\nAlpha,10\n", encoding="utf-8")

    result = SpreadsheetIngestionAdapter().extract(
        source(path, "text/csv"), configuration(header_row=2), Control()
    )

    assert result.content_units[0].structured_data == {"Name": "Alpha", "Value": "10"}
    assert result.content_units[0].source_locator["row_number"] == 3


def test_extract_checks_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("Name,Value\nAlpha,10\nBeta,20\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="cancelled"):
        SpreadsheetIngestionAdapter().extract(
            source(path, "text/csv"), configuration(), Control(cancel_after=1)
        )


def test_adapter_has_no_profiles_provider_or_persistence_state() -> None:
    adapter = SpreadsheetIngestionAdapter()
    assert adapter.capabilities.supports_structured_output is True
    assert adapter.capabilities.requires_external_binary is False
    assert not hasattr(adapter, "sheet_profiles")
    assert not hasattr(adapter, "session")
    assert not hasattr(adapter, "repository")
    assert not hasattr(adapter, "provider")
