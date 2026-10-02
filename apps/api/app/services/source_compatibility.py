from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class CompatibilityLevel(StrEnum):
    NATIVE = "native"
    OPTIONAL_DEPENDENCY = "optional_dependency"
    CONTAINER_EXPANSION = "container_expansion"
    PLANNED = "planned"


class SourceFamily(StrEnum):
    TEXT = "text"
    RICH_DOCUMENT = "rich_document"
    SPREADSHEET = "spreadsheet"
    IMAGE = "image"
    EMAIL = "email"
    STRUCTURED = "structured"
    ARCHIVE = "archive"
    DRAWING = "drawing"


@dataclass(frozen=True)
class SourceFormat:
    key: str
    family: SourceFamily
    extensions: tuple[str, ...]
    media_types: tuple[str, ...]
    preferred_adapter: str
    fallback_adapters: tuple[str, ...] = ()
    compatibility: CompatibilityLevel = CompatibilityLevel.NATIVE
    requires_ocr: bool = False
    requires_external_binary: bool = False
    container_format: bool = False


FORMAT_REGISTRY: tuple[SourceFormat, ...] = (
    SourceFormat(
        "plain-text",
        SourceFamily.TEXT,
        (".txt", ".log", ".cfg", ".conf", ".ini", ".properties"),
        ("text/plain",),
        "text",
    ),
    SourceFormat("markdown", SourceFamily.TEXT, (".md", ".markdown", ".rst"), ("text/markdown", "text/x-rst"), "text"),
    SourceFormat(
        "html",
        SourceFamily.TEXT,
        (".html", ".htm", ".xhtml"),
        ("text/html", "application/xhtml+xml"),
        "text",
        ("rich-document",),
    ),
    SourceFormat(
        "xml",
        SourceFamily.STRUCTURED,
        (".xml", ".xsd", ".xsl", ".xslt", ".svg"),
        ("application/xml", "text/xml", "image/svg+xml"),
        "text",
    ),
    SourceFormat(
        "json",
        SourceFamily.STRUCTURED,
        (".json", ".jsonl"),
        ("application/json", "application/jsonlines"),
        "text",
        ("ndjson",),
    ),
    SourceFormat(
        "yaml",
        SourceFamily.STRUCTURED,
        (".yaml", ".yml"),
        ("application/yaml", "text/yaml", "application/x-yaml"),
        "text",
    ),
    SourceFormat("ndjson", SourceFamily.STRUCTURED, (".ndjson",), ("application/x-ndjson",), "ndjson"),
    SourceFormat(
        "csv",
        SourceFamily.SPREADSHEET,
        (".csv", ".tsv"),
        ("text/csv", "text/tab-separated-values"),
        "spreadsheet",
        ("text",),
    ),
    SourceFormat(
        "pdf",
        SourceFamily.RICH_DOCUMENT,
        (".pdf",),
        ("application/pdf",),
        "rich-document",
        (),
        CompatibilityLevel.NATIVE,
    ),
    SourceFormat(
        "word-openxml",
        SourceFamily.RICH_DOCUMENT,
        (".docx", ".docm", ".dotx"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "word-legacy",
        SourceFamily.RICH_DOCUMENT,
        (".doc", ".dot"),
        ("application/msword",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "open-document-text",
        SourceFamily.RICH_DOCUMENT,
        (".odt",),
        ("application/vnd.oasis.opendocument.text",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "rich-text",
        SourceFamily.RICH_DOCUMENT,
        (".rtf",),
        ("application/rtf", "text/rtf"),
        "rich-document",
        ("text",),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "presentation-openxml",
        SourceFamily.RICH_DOCUMENT,
        (".pptx", ".pptm", ".potx"),
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "presentation-legacy",
        SourceFamily.RICH_DOCUMENT,
        (".ppt", ".pps"),
        ("application/vnd.ms-powerpoint",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "open-document-presentation",
        SourceFamily.RICH_DOCUMENT,
        (".odp",),
        ("application/vnd.oasis.opendocument.presentation",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_external_binary=True,
    ),
    SourceFormat(
        "epub",
        SourceFamily.RICH_DOCUMENT,
        (".epub",),
        ("application/epub+zip",),
        "rich-document",
        ("archive",),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "excel-openxml",
        SourceFamily.SPREADSHEET,
        (".xlsx", ".xlsm", ".xltx"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
        "spreadsheet",
    ),
    SourceFormat(
        "excel-legacy",
        SourceFamily.SPREADSHEET,
        (".xls", ".xlt"),
        ("application/vnd.ms-excel",),
        "spreadsheet",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "excel-binary",
        SourceFamily.SPREADSHEET,
        (".xlsb",),
        ("application/vnd.ms-excel.sheet.binary.macroenabled.12",),
        "spreadsheet",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "open-document-spreadsheet",
        SourceFamily.SPREADSHEET,
        (".ods",),
        ("application/vnd.oasis.opendocument.spreadsheet",),
        "spreadsheet",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "parquet",
        SourceFamily.STRUCTURED,
        (".parquet",),
        ("application/vnd.apache.parquet",),
        "structured-table",
        (),
        CompatibilityLevel.PLANNED,
    ),
    SourceFormat(
        "avro",
        SourceFamily.STRUCTURED,
        (".avro",),
        ("application/avro",),
        "structured-record",
        (),
        CompatibilityLevel.PLANNED,
    ),
    SourceFormat(
        "image-raster",
        SourceFamily.IMAGE,
        (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"),
        ("image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
        requires_ocr=True,
        requires_external_binary=True,
    ),
    SourceFormat(
        "image-heic",
        SourceFamily.IMAGE,
        (".heic", ".heif"),
        ("image/heic", "image/heif"),
        "rich-document",
        (),
        CompatibilityLevel.PLANNED,
        requires_ocr=True,
        requires_external_binary=True,
    ),
    SourceFormat(
        "email-eml",
        SourceFamily.EMAIL,
        (".eml",),
        ("message/rfc822",),
        "rich-document",
        ("text",),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "email-msg",
        SourceFamily.EMAIL,
        (".msg",),
        ("application/vnd.ms-outlook",),
        "rich-document",
        (),
        CompatibilityLevel.OPTIONAL_DEPENDENCY,
    ),
    SourceFormat(
        "email-mbox",
        SourceFamily.EMAIL,
        (".mbox",),
        ("application/mbox",),
        "email-container",
        (),
        CompatibilityLevel.PLANNED,
        container_format=True,
    ),
    SourceFormat(
        "zip",
        SourceFamily.ARCHIVE,
        (".zip",),
        ("application/zip",),
        "archive",
        (),
        CompatibilityLevel.CONTAINER_EXPANSION,
        container_format=True,
    ),
    SourceFormat(
        "tar",
        SourceFamily.ARCHIVE,
        (".tar", ".tgz", ".tar.gz", ".gz"),
        ("application/x-tar", "application/gzip"),
        "archive",
        (),
        CompatibilityLevel.CONTAINER_EXPANSION,
        container_format=True,
    ),
    SourceFormat(
        "seven-zip",
        SourceFamily.ARCHIVE,
        (".7z",),
        ("application/x-7z-compressed",),
        "archive",
        (),
        CompatibilityLevel.PLANNED,
        container_format=True,
        requires_external_binary=True,
    ),
    SourceFormat(
        "drawing-dxf", SourceFamily.DRAWING, (".dxf",), ("image/vnd.dxf",), "drawing", (), CompatibilityLevel.PLANNED
    ),
    SourceFormat(
        "drawing-dwg",
        SourceFamily.DRAWING,
        (".dwg",),
        ("image/vnd.dwg",),
        "drawing",
        (),
        CompatibilityLevel.PLANNED,
        requires_external_binary=True,
    ),
)


class SourceCompatibilityError(ValueError):
    pass


def normalized_extension(file_name: str) -> str:
    lowered = file_name.strip().lower()
    for candidate in (".tar.gz",):
        if lowered.endswith(candidate):
            return candidate
    if "." not in lowered:
        return ""
    return "." + lowered.rsplit(".", 1)[1]


def resolve_source_format(file_name: str, media_type: str | None = None) -> SourceFormat:
    extension = normalized_extension(file_name)
    normalized_media_type = (media_type or "").split(";", 1)[0].strip().lower()
    matches = [
        item
        for item in FORMAT_REGISTRY
        if (extension and extension in item.extensions)
        or (normalized_media_type and normalized_media_type in item.media_types)
    ]
    if not matches:
        raise SourceCompatibilityError("unsupported source format")

    exact = [item for item in matches if extension in item.extensions and normalized_media_type in item.media_types]
    candidates = exact or matches
    keys = {item.key for item in candidates}
    if len(keys) != 1:
        raise SourceCompatibilityError("ambiguous source format")
    return candidates[0]


def compatibility_summary(items: Iterable[SourceFormat] = FORMAT_REGISTRY) -> dict[str, int]:
    values = list(items)
    return {
        "formats": len(values),
        "extensions": len({ext for item in values for ext in item.extensions}),
        "media_types": len({media for item in values for media in item.media_types}),
        "native": sum(item.compatibility == CompatibilityLevel.NATIVE for item in values),
        "optional_dependency": sum(item.compatibility == CompatibilityLevel.OPTIONAL_DEPENDENCY for item in values),
        "container_expansion": sum(item.compatibility == CompatibilityLevel.CONTAINER_EXPANSION for item in values),
        "planned": sum(item.compatibility == CompatibilityLevel.PLANNED for item in values),
    }
