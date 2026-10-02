from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.services.artifact_reconciliation import ArtifactObjectMetadata


class S3ArtifactObjectStore:
    """Read-only S3-compatible metadata adapter used by reconciliation."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str = "us-east-1",
        use_ssl: bool = False,
        client: Any | None = None,
    ) -> None:
        if not endpoint_url.strip():
            raise ValueError("object storage endpoint is required")
        if not access_key_id.strip():
            raise ValueError("object storage access key is required")
        if not secret_access_key.strip():
            raise ValueError("object storage secret key is required")
        if not bucket.strip():
            raise ValueError("object storage bucket is required")

        self.bucket = bucket.strip()
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url.strip(),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region.strip() or "us-east-1",
            use_ssl=use_ssl,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )

    def stat(self, storage_uri: str) -> ArtifactObjectMetadata | None:
        bucket, key = self._resolve_location(storage_uri)
        try:
            response = self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

        metadata = response.get("Metadata") or {}
        return ArtifactObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            checksum_sha256=metadata.get("sha256"),
            media_type=response.get("ContentType"),
        )

    def _resolve_location(self, storage_uri: str) -> tuple[str, str]:
        value = storage_uri.strip() if isinstance(storage_uri, str) else ""
        if not value:
            raise ValueError("storage_uri is required")

        if value.startswith("s3://"):
            parsed = urlparse(value)
            bucket = parsed.netloc.strip()
            key = parsed.path.lstrip("/")
            if bucket != self.bucket:
                raise ValueError("storage_uri bucket does not match configured bucket")
        else:
            bucket = self.bucket
            key = value.lstrip("/")

        if not key:
            raise ValueError("storage_uri object key is required")
        return bucket, key
