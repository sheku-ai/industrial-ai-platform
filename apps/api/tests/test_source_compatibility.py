from app.services.source_compatibility import (
    CompatibilityLevel,
    SourceCompatibilityError,
    compatibility_summary,
    resolve_source_format,
)


def test_registry_covers_broad_document_families() -> None:
    summary = compatibility_summary()

    assert summary["formats"] >= 30
    assert summary["extensions"] >= 60
    assert summary["media_types"] >= 35


def test_resolves_common_enterprise_formats() -> None:
    cases = {
        "document.pdf": "pdf",
        "document.docx": "word-openxml",
        "presentation.pptx": "presentation-openxml",
        "workbook.xlsx": "excel-openxml",
        "message.eml": "email-eml",
        "image.tiff": "image-raster",
        "payload.ndjson": "ndjson",
        "archive.zip": "zip",
        "config.yaml": "yaml",
    }

    for file_name, expected in cases.items():
        assert resolve_source_format(file_name).key == expected


def test_media_type_parameters_are_ignored() -> None:
    resolved = resolve_source_format("source.txt", "text/plain; charset=utf-8")
    assert resolved.key == "plain-text"


def test_optional_and_planned_formats_remain_explicit() -> None:
    assert resolve_source_format("source.docx").compatibility == CompatibilityLevel.OPTIONAL_DEPENDENCY
    assert resolve_source_format("source.dwg").compatibility == CompatibilityLevel.PLANNED
    assert resolve_source_format("source.zip").compatibility == CompatibilityLevel.CONTAINER_EXPANSION


def test_unsupported_format_is_rejected() -> None:
    try:
        resolve_source_format("source.unknown")
    except SourceCompatibilityError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported format was accepted")
