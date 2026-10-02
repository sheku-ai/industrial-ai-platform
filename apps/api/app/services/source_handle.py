from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.services.ingestion_contracts import IngestionContractError

DEFAULT_STREAM_CHUNK_SIZE = 1024 * 1024


class SourceHandle(Protocol):
    source_reference: str
    detected_media_type: str
    content_length: int
    checksum_sha256: str | None

    def iter_bytes(
        self, *, start: int = 0, end_exclusive: int | None = None, chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE
    ) -> Iterator[bytes]: ...

    def materialize(self, destination: Path) -> Path: ...


@dataclass(frozen=True)
class LocalFileSourceHandle:
    source_reference: str
    local_path: Path
    detected_media_type: str
    content_length: int
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.source_reference.strip():
            raise IngestionContractError("source_reference is required")
        if self.content_length < 0:
            raise IngestionContractError("content_length must be non-negative")
        if not self.local_path.is_file():
            raise IngestionContractError("local source path does not exist")
        if self.local_path.stat().st_size != self.content_length:
            raise IngestionContractError("local source length does not match content_length")

    def iter_bytes(
        self, *, start: int = 0, end_exclusive: int | None = None, chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE
    ) -> Iterator[bytes]:
        _validate_range(self.content_length, start, end_exclusive, chunk_size)
        remaining = self.content_length - start if end_exclusive is None else end_exclusive - start
        with self.local_path.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                block = handle.read(min(chunk_size, remaining))
                if not block:
                    raise IngestionContractError("source range could not be fully read")
                remaining -= len(block)
                yield block

    def materialize(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with destination.open("wb") as output:
            for block in self.iter_bytes():
                output.write(block)
                digest.update(block)
                written += len(block)
        if written != self.content_length:
            destination.unlink(missing_ok=True)
            raise IngestionContractError("materialized length mismatch")
        if self.checksum_sha256 is not None and digest.hexdigest() != self.checksum_sha256:
            destination.unlink(missing_ok=True)
            raise IngestionContractError("materialized checksum mismatch")
        return destination


def _validate_range(content_length: int, start: int, end_exclusive: int | None, chunk_size: int) -> None:
    if start < 0 or start > content_length:
        raise IngestionContractError("range start is outside the source")
    if end_exclusive is not None and (end_exclusive < start or end_exclusive > content_length):
        raise IngestionContractError("range end is outside the source")
    if chunk_size <= 0:
        raise IngestionContractError("chunk_size must be positive")
