from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class S3ObjectMetadata:
    size_bytes: int
    checksum_sha256: str | None
    content_type: str | None


class S3CompatibleObjectStore:
    """Explicit-endpoint S3 adapter for isolated integration scenarios."""

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
            raise ValueError("endpoint_url is required")
        if not access_key_id.strip():
            raise ValueError("access_key_id is required")
        if not secret_access_key.strip():
            raise ValueError("secret_access_key is required")
        if not bucket.strip():
            raise ValueError("bucket is required")

        self.bucket = bucket.strip()
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url.strip(),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            use_ssl=use_ssl,
            config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
        )

    def put_bytes(self, key: str, payload: bytes, *, content_type: str | None = None) -> str:
        canonical_key = self._validate_key(key)
        checksum = sha256(payload).hexdigest()
        metadata = {"sha256": checksum}
        kwargs = {
            "Bucket": self.bucket,
            "Key": canonical_key,
            "Body": payload,
            "Metadata": metadata,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return checksum

    def stat(self, key: str) -> S3ObjectMetadata | None:
        canonical_key = self._validate_key(key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=canonical_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = response.get("Metadata") or {}
        return S3ObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            checksum_sha256=metadata.get("sha256"),
            content_type=response.get("ContentType"),
        )

    def read_bytes(self, key: str) -> bytes:
        canonical_key = self._validate_key(key)
        response = self.client.get_object(Bucket=self.bucket, Key=canonical_key)
        return response["Body"].read()

    def remove(self, key: str) -> None:
        canonical_key = self._validate_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=canonical_key)

    @staticmethod
    def _validate_key(key: str) -> str:
        canonical_key = key.strip() if isinstance(key, str) else ""
        if not canonical_key:
            raise ValueError("object key is required")
        if canonical_key.startswith("/"):
            raise ValueError("object key must be relative")
        return canonical_key
