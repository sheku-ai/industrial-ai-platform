from __future__ import annotations

import csv
import html
import io
import json
import re
from dataclasses import dataclass

from app.services.ingestion_adapter_contracts import (
    AdapterChunk,
    AdapterExecutionResult,
    AdapterExecutionStatus,
    AdapterInput,
)
from app.services.source_compatibility import resolve_source_format


@dataclass(frozen=True)
class TextAdapterOptions:
    max_chars: int = 1200
    overlap: int = 200
    min_chunk_chars: int = 40

    def __post_init__(self) -> None:
        if self.max_chars < 200:
            raise ValueError("max_chars must be at least 200")
        if self.overlap < 0 or self.overlap >= self.max_chars:
            raise ValueError("invalid overlap")


def decode_text(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("source payload could not be decoded")


def normalize_text(text: str) -> str:
    text = text.replace(chr(0), " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def preprocess(text: str, format_key: str) -> str:
    if format_key == "html":
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        return normalize_text(html.unescape(text))
    if format_key == "xml":
        text = re.sub(r"<[^>]+>", " ", text)
        return normalize_text(html.unescape(text))
    if format_key == "json":
        try:
            return normalize_text(json.dumps(json.loads(text), ensure_ascii=False, indent=2, sort_keys=True))
        except json.JSONDecodeError:
            return normalize_text(text)
    if format_key == "csv":
        delimiter = "\t" if text.splitlines() and "\t" in text.splitlines()[0] else ","
        rows = csv.reader(io.StringIO(text), delimiter=delimiter)
        return normalize_text("\n".join(" | ".join(cell.strip() for cell in row) for row in rows))
    return normalize_text(text)


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        value = text[start:end].strip()
        if value:
            chunks.append(value)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


class TextIngestionAdapter:
    def execute_bytes(
        self, request: AdapterInput, payload: bytes, options: TextAdapterOptions | None = None
    ) -> AdapterExecutionResult:
        options = options or TextAdapterOptions()
        source_format = resolve_source_format(request.original_file_name, request.declared_media_type)
        if source_format.preferred_adapter not in {"text", "spreadsheet"}:
            return AdapterExecutionResult(
                status=AdapterExecutionStatus.FAILED,
                error_code="unsupported_text_adapter_format",
                error_message=f"format {source_format.key} requires adapter {source_format.preferred_adapter}",
            )
        try:
            decoded, encoding = decode_text(payload)
            normalized = preprocess(decoded, source_format.key)
        except ValueError as exc:
            return AdapterExecutionResult(
                status=AdapterExecutionStatus.FAILED,
                error_code="text_decode_failed",
                error_message=str(exc),
            )
        chunks = tuple(
            AdapterChunk(
                chunk_index=index,
                text=value,
                content_type=request.declared_media_type or "text/plain",
                section_ref={"part": index},
                provenance={"adapter": "text", "format": source_format.key, "encoding": encoding},
                quality={"accepted": len(value) >= options.min_chunk_chars, "char_count": len(value)},
                metadata={"original_file_name": request.original_file_name},
            )
            for index, value in enumerate(chunk_text(normalized, options.max_chars, options.overlap))
        )
        if not chunks:
            return AdapterExecutionResult(
                status=AdapterExecutionStatus.FAILED,
                error_code="empty_text_content",
                error_message="source produced no text",
            )
        return AdapterExecutionResult(
            status=AdapterExecutionStatus.SUCCEEDED,
            chunks=chunks,
            metrics={
                "adapter": "text",
                "format": source_format.key,
                "encoding": encoding,
                "source_bytes": len(payload),
                "normalized_chars": len(normalized),
                "chunk_count": len(chunks),
                "embedding_generated": False,
                "vector_indexed": False,
                "llm_used": False,
            },
        )
