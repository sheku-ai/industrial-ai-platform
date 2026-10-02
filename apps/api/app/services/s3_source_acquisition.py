from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import boto3

from app.core.config import get_settings
from app.services.ingestion_contracts import AcquiredSource, IngestionContractError
from app.services.source_handle import DEFAULT_STREAM_CHUNK_SIZE, _validate_range


@dataclass(frozen=True)
class S3SourceHandle:
    source_reference: str
    bucket: str
    key: str
    detected_media_type: str
    content_length: int
    checksum_sha256: str | None
    client: object

    def iter_bytes(
        self,
        *,
        start: int = 0,
        end_exclusive: int | None = None,
        chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        _validate_range(self.content_length, start, end_exclusive, chunk_size)
        if start == self.content_length:
            return
        end_inclusive = self.content_length - 1 if end_exclusive is None else end_exclusive - 1
        if end_inclusive < start:
            return
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=self.key,
            Range=f"bytes={start}-{end_inclusive}",
        )
        body = response["Body"]
        remaining = end_inclusive - start + 1
        try:
            while remaining > 0:
                block = body.read(min(chunk_size, remaining))
                if not block:
                    raise IngestionContractError("object range could not be fully read")
                remaining -= len(block)
                yield block
        finally:
            body.close()

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
            raise IngestionContractError("materialized source length mismatch")
        checksum = digest.hexdigest()
        if self.checksum_sha256 is not None and checksum != self.checksum_sha256:
            destination.unlink(missing_ok=True)
            raise IngestionContractError("materialized source checksum mismatch")
        return destination


class S3SourceAcquisitionService:
    def __init__(self, *, workspace_root: str = "/app/runtime/ingestion") -> None:
        settings = get_settings()
        self._workspace_root = Path(os.getenv("INGESTION_WORKSPACE_ROOT", workspace_root))
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url or None,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key or None,
            aws_secret_access_key=settings.object_storage_secret_key or None,
            use_ssl=settings.object_storage_secure,
        )

    def open_handle(self, source_reference: str) -> S3SourceHandle:
        parsed = urlparse(source_reference)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
            raise IngestionContractError("source_reference must be an s3:// URI")
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        head = self._client.head_object(Bucket=bucket, Key=key)
        checksum = head.get("Metadata", {}).get("sha256")
        if checksum is not None:
            checksum = str(checksum).lower()
        return S3SourceHandle(
            source_reference=source_reference,
            bucket=bucket,
            key=key,
            detected_media_type=str(head.get("ContentType") or "application/octet-stream"),
            content_length=int(head.get("ContentLength", 0)),
            checksum_sha256=checksum,
            client=self._client,
        )

    def acquire(self, organization_id, source_reference, *, execution_id, attempt_number):
        handle = self.open_handle(source_reference)
        workspace = self._workspace_root / str(organization_id) / str(execution_id) / str(attempt_number)
        local_path = workspace / Path(handle.key).name
        handle.materialize(local_path)
        digest = hashlib.sha256()
        with local_path.open("rb") as source:
            for block in iter(lambda: source.read(DEFAULT_STREAM_CHUNK_SIZE), b""):
                digest.update(block)
        checksum = digest.hexdigest()
        return AcquiredSource(
            source_reference=source_reference,
            local_path=str(local_path),
            detected_media_type=handle.detected_media_type,
            content_length=handle.content_length,
            checksum_sha256=checksum,
        )
