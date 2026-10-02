from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.services.ingestion_contracts import IngestionContractError
from app.services.source_acquisition import SourceObjectDescriptor


@dataclass(frozen=True)
class ObjectLocation:
    bucket: str
    key: str


class S3CompatibleSourceObjectReader:
    """Read tenant-scoped objects through an S3-compatible client."""

    def __init__(self, client, *, required_bucket: str | None = None) -> None:
        self._client = client
        self._required_bucket = required_bucket

    def describe(self, organization_id: UUID, source_reference: str) -> SourceObjectDescriptor:
        location = self._parse_location(organization_id, source_reference)
        response = self._client.head_object(Bucket=location.bucket, Key=location.key)
        metadata = {str(k).lower(): str(v) for k, v in response.get("Metadata", {}).items()}
        checksum = metadata.get("sha256")
        if checksum is None:
            raise IngestionContractError("source object is missing sha256 metadata")

        length = response.get("ContentLength")
        if not isinstance(length, int) or length < 0:
            raise IngestionContractError("source object content length is invalid")

        media_type = response.get("ContentType") or "application/octet-stream"
        file_name = location.key.rsplit("/", 1)[-1] or "source.bin"
        return SourceObjectDescriptor(
            source_reference=source_reference,
            media_type=media_type,
            content_length=length,
            checksum_sha256=checksum.lower(),
            file_name=file_name,
        )

    def open_stream(self, organization_id: UUID, source_reference: str) -> BinaryIO:
        location = self._parse_location(organization_id, source_reference)
        response = self._client.get_object(Bucket=location.bucket, Key=location.key)
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise IngestionContractError("source object body is not readable")
        return body

    def _parse_location(self, organization_id: UUID, source_reference: str) -> ObjectLocation:
        parsed = urlparse(source_reference)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise IngestionContractError("source_reference must use s3://bucket/key")
        bucket = parsed.netloc
        key = unquote(parsed.path.lstrip("/"))
        if not key:
            raise IngestionContractError("source object key is required")
        if self._required_bucket is not None and bucket != self._required_bucket:
            raise IngestionContractError("source object bucket is not allowed")
        expected_prefix = f"{organization_id}/"
        if not key.startswith(expected_prefix):
            raise IngestionContractError("source object is outside organization namespace")
        return ObjectLocation(bucket=bucket, key=key)
