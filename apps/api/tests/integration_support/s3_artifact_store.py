from __future__ import annotations

from urllib.parse import urlparse

from app.services.artifact_reconciliation import ArtifactObjectMetadata
from tests.integration_support.s3_object_store import S3CompatibleObjectStore


class S3ArtifactObjectStoreAdapter:
    def __init__(self, store: S3CompatibleObjectStore, *, bucket: str) -> None:
        self.store = store
        self.bucket = bucket

    def stat(self, storage_uri: str) -> ArtifactObjectMetadata | None:
        key = self._key_from_uri(storage_uri)
        metadata = self.store.stat(key)
        if metadata is None:
            return None
        return ArtifactObjectMetadata(
            size_bytes=metadata.size_bytes,
            checksum_sha256=metadata.checksum_sha256,
            media_type=metadata.content_type,
        )

    def _key_from_uri(self, storage_uri: str) -> str:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3":
            raise ValueError("storage_uri must use the s3 scheme")
        if parsed.netloc != self.bucket:
            raise ValueError("storage_uri bucket does not match configured bucket")
        key = parsed.path.lstrip("/")
        if not key:
            raise ValueError("storage_uri object key is required")
        return key
