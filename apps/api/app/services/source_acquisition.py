from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID

from app.services.ingestion_contracts import AcquiredSource, IngestionContractError


@dataclass(frozen=True)
class SourceObjectDescriptor:
    source_reference: str
    media_type: str
    content_length: int
    checksum_sha256: str
    file_name: str


class SourceObjectReader(Protocol):
    def describe(
        self,
        organization_id: UUID,
        source_reference: str,
    ) -> SourceObjectDescriptor: ...

    def open_stream(
        self,
        organization_id: UUID,
        source_reference: str,
    ) -> BinaryIO: ...


class WorkspaceSourceAcquisitionService:
    """Acquire an opaque source object into an isolated local workspace."""

    def __init__(
        self,
        reader: SourceObjectReader,
        workspace_root: Path,
        *,
        max_source_bytes: int = 1_000_000_000,
    ) -> None:
        if max_source_bytes <= 0:
            raise IngestionContractError("max_source_bytes must be positive")
        self._reader = reader
        self._workspace_root = workspace_root.resolve()
        self._max_source_bytes = max_source_bytes

    def acquire(
        self,
        organization_id: UUID,
        source_reference: str,
        *,
        execution_id: UUID,
        attempt_number: int,
    ) -> AcquiredSource:
        if not source_reference.strip():
            raise IngestionContractError("source_reference is required")
        if attempt_number <= 0:
            raise IngestionContractError("attempt_number must be positive")

        descriptor = self._reader.describe(organization_id, source_reference)
        self._validate_descriptor(descriptor, source_reference)

        workspace = self._workspace_root / str(organization_id) / str(execution_id) / str(attempt_number)
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / _safe_file_name(descriptor.file_name)
        partial = target.with_suffix(target.suffix + ".partial")

        digest = sha256()
        written = 0
        try:
            with (
                self._reader.open_stream(organization_id, source_reference) as source,
                partial.open("wb") as output,
            ):
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    if not isinstance(block, bytes | bytearray):
                        raise IngestionContractError("source reader returned non-binary content")
                    written += len(block)
                    if written > self._max_source_bytes:
                        raise IngestionContractError("source exceeds configured acquisition limit")
                    digest.update(block)
                    output.write(block)

            if written != descriptor.content_length:
                raise IngestionContractError("acquired source length does not match object descriptor")
            if digest.hexdigest() != descriptor.checksum_sha256:
                raise IngestionContractError("acquired source checksum does not match object descriptor")

            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        return AcquiredSource(
            source_reference=descriptor.source_reference,
            local_path=str(target),
            detected_media_type=descriptor.media_type,
            content_length=written,
            checksum_sha256=digest.hexdigest(),
        )

    def _validate_descriptor(
        self,
        descriptor: SourceObjectDescriptor,
        requested_reference: str,
    ) -> None:
        if descriptor.source_reference != requested_reference:
            raise IngestionContractError("source descriptor reference mismatch")
        if descriptor.content_length < 0:
            raise IngestionContractError("source descriptor length cannot be negative")
        if descriptor.content_length > self._max_source_bytes:
            raise IngestionContractError("source exceeds configured acquisition limit")
        if not _is_sha256(descriptor.checksum_sha256):
            raise IngestionContractError("source descriptor checksum must be lowercase SHA-256")
        if not descriptor.media_type.strip() or "/" not in descriptor.media_type:
            raise IngestionContractError("source descriptor media type is invalid")


def _safe_file_name(value: str) -> str:
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        return "source.bin"
    sanitized = "".join(character if character.isalnum() or character in {".", "-", "_"} else "_" for character in name)
    return sanitized[:255] or "source.bin"


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and all(character in "0123456789abcdef" for character in value)
