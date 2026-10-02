from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

from app.services.knowledge_artifact_storage import StoredArtifactInfo


class MinioArtifactStorageAdapter:
    """Adapts a MinIO-compatible client to the artifact storage port."""

    def __init__(self, client: Any, *, bucket_name: str) -> None:
        bucket_name = bucket_name.strip()
        if not bucket_name:
            raise ValueError("bucket_name is required")
        self.client = client
        self.bucket_name = bucket_name

    def inspect(self, object_name: str) -> StoredArtifactInfo | None:
        try:
            stat = self.client.stat_object(self.bucket_name, object_name)
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise

        metadata = _normalize_metadata(getattr(stat, "metadata", None))
        return StoredArtifactInfo(
            object_name=object_name,
            size_bytes=int(stat.size),
            sha256=metadata.get("sha256", ""),
            content_type=(metadata.get("content-type") or metadata.get("content_type") or "application/octet-stream"),
            version_tag=(
                str(stat.version_id)
                if getattr(stat, "version_id", None) is not None
                else str(getattr(stat, "etag", "")) or None
            ),
        )

    def write(
        self,
        object_name: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredArtifactInfo:
        normalized_metadata = {str(key): str(value) for key, value in metadata.items()}
        self.client.put_object(
            self.bucket_name,
            object_name,
            io.BytesIO(payload),
            len(payload),
            content_type=content_type,
            metadata=normalized_metadata,
        )
        stored = self.inspect(object_name)
        if stored is None:
            raise RuntimeError("object was not visible after upload")
        return stored


def _normalize_metadata(value: Any) -> dict[str, str]:
    if not value:
        return {}
    normalized: dict[str, str] = {}
    for key, item in dict(value).items():
        name = str(key).lower()
        if name.startswith("x-amz-meta-"):
            name = name[len("x-amz-meta-") :]
        normalized[name] = str(item)
    return normalized


def _is_not_found(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error") or response.get("error") or {}
        if isinstance(error, Mapping) and error.get("Code") in {
            "NoSuchKey",
            "NoSuchObject",
            "NotFound",
        }:
            return True
    return False
