from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from botocore.exceptions import ClientError

from app.services.knowledge_artifact_storage import StoredArtifactInfo


class S3ArtifactStorageAdapter:
    """Adapts a boto3 S3 client to the artifact storage port."""

    def __init__(self, client: Any, *, bucket_name: str) -> None:
        bucket_name = bucket_name.strip()
        if not bucket_name:
            raise ValueError("bucket_name is required")
        self.client = client
        self.bucket_name = bucket_name

    def ensure_bucket(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            return False
        except ClientError as exc:
            status = _status_code(exc)
            if status not in {404, 403}:
                raise
            if status == 403:
                raise
        self.client.create_bucket(Bucket=self.bucket_name)
        return True

    def inspect(self, object_name: str) -> StoredArtifactInfo | None:
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=object_name)
        except ClientError as exc:
            if _status_code(exc) == 404 or _error_code(exc) in {"NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = {str(key).lower(): str(value) for key, value in dict(response.get("Metadata") or {}).items()}
        return StoredArtifactInfo(
            object_name=object_name,
            size_bytes=int(response.get("ContentLength", 0)),
            sha256=metadata.get("sha256", ""),
            content_type=str(response.get("ContentType") or "application/octet-stream"),
            version_tag=(
                str(response.get("VersionId"))
                if response.get("VersionId") is not None
                else str(response.get("ETag") or "").strip('"') or None
            ),
        )

    def write(
        self, object_name: str, payload: bytes, *, content_type: str, metadata: Mapping[str, str]
    ) -> StoredArtifactInfo:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=object_name,
            Body=payload,
            ContentType=content_type,
            Metadata={str(key): str(value) for key, value in metadata.items()},
        )
        stored = self.inspect(object_name)
        if stored is None:
            raise RuntimeError("object was not visible after upload")
        return stored

    def remove(self, object_name: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=object_name)


def _status_code(exc: ClientError) -> int | None:
    response = getattr(exc, "response", {}) or {}
    metadata = response.get("ResponseMetadata") or {}
    value = metadata.get("HTTPStatusCode")
    return int(value) if value is not None else None


def _error_code(exc: ClientError) -> str | None:
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error") or {}
    value = error.get("Code")
    return str(value) if value is not None else None
