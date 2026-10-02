from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.services.ingestion_contracts import IngestionContractError


@dataclass(frozen=True)
class PresignedUpload:
    bucket: str
    key: str
    url: str
    method: str
    required_headers: dict[str, str]
    expires_in_seconds: int


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    content_length: int
    content_type: str
    checksum_sha256: str


class S3CompatibleUploadService:
    def __init__(self, client, *, bucket: str, expires_in_seconds: int = 900) -> None:
        if not bucket.strip():
            raise IngestionContractError("object storage bucket is required")
        if expires_in_seconds <= 0:
            raise IngestionContractError("upload URL expiry must be positive")
        self._client = client
        self._bucket = bucket
        self._expires_in_seconds = expires_in_seconds

    def create_upload(
        self,
        organization_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        *,
        file_name: str,
        content_type: str,
        checksum_sha256: str,
    ) -> PresignedUpload:
        safe_name = _safe_file_name(file_name)
        checksum = _validate_sha256(checksum_sha256)
        key = f"{organization_id}/{document_id}/{document_version_id}/{safe_name}"
        params = {
            "Bucket": self._bucket,
            "Key": key,
            "ContentType": content_type,
            "Metadata": {"sha256": checksum},
        }
        url = self._client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=self._expires_in_seconds,
            HttpMethod="PUT",
        )
        return PresignedUpload(
            bucket=self._bucket,
            key=key,
            url=url,
            method="PUT",
            required_headers={
                "Content-Type": content_type,
                "x-amz-meta-sha256": checksum,
            },
            expires_in_seconds=self._expires_in_seconds,
        )

    def verify_upload(self, *, bucket: str, key: str) -> StoredObject:
        if bucket != self._bucket:
            raise IngestionContractError("object storage bucket is not allowed")
        response = self._client.head_object(Bucket=bucket, Key=key)
        metadata = {str(k).lower(): str(v) for k, v in response.get("Metadata", {}).items()}
        checksum = metadata.get("sha256")
        if checksum is None:
            raise IngestionContractError("stored object is missing sha256 metadata")
        length = response.get("ContentLength")
        if not isinstance(length, int) or length < 0:
            raise IngestionContractError("stored object content length is invalid")
        return StoredObject(
            bucket=bucket,
            key=key,
            content_length=length,
            content_type=response.get("ContentType") or "application/octet-stream",
            checksum_sha256=_validate_sha256(checksum),
        )


def _safe_file_name(value: str) -> str:
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        raise IngestionContractError("file name is required")
    safe = "".join(character if character.isalnum() or character in {".", "-", "_"} else "_" for character in name)
    return safe[:255] or "source.bin"


def _validate_sha256(value: str) -> str:
    checksum = value.strip().lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise IngestionContractError("checksum must be lowercase SHA-256")
    return checksum
