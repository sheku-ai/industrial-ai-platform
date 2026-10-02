from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.infrastructure.s3_artifact_object_store import S3ArtifactObjectStore


def _store(client: MagicMock) -> S3ArtifactObjectStore:
    return S3ArtifactObjectStore(
        endpoint_url="http://localhost:9000",
        access_key_id="access",
        secret_access_key="secret",
        bucket="artifacts",
        client=client,
    )


def test_stat_reads_metadata_from_relative_key() -> None:
    client = MagicMock()
    client.head_object.return_value = {
        "ContentLength": 12,
        "ContentType": "text/plain",
        "Metadata": {"sha256": "abc123"},
    }

    metadata = _store(client).stat("runtime/object.txt")

    client.head_object.assert_called_once_with(
        Bucket="artifacts",
        Key="runtime/object.txt",
    )
    assert metadata is not None
    assert metadata.size_bytes == 12
    assert metadata.checksum_sha256 == "abc123"
    assert metadata.media_type == "text/plain"


def test_stat_accepts_matching_s3_uri() -> None:
    client = MagicMock()
    client.head_object.return_value = {
        "ContentLength": 0,
        "Metadata": {},
    }

    metadata = _store(client).stat("s3://artifacts/path/item.bin")

    client.head_object.assert_called_once_with(
        Bucket="artifacts",
        Key="path/item.bin",
    )
    assert metadata is not None
    assert metadata.size_bytes == 0


def test_stat_rejects_cross_bucket_uri() -> None:
    with pytest.raises(ValueError):
        _store(MagicMock()).stat("s3://other-bucket/path/item.bin")


def test_stat_returns_none_for_missing_object() -> None:
    client = MagicMock()
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
        "HeadObject",
    )

    assert _store(client).stat("missing.bin") is None


def test_stat_propagates_non_missing_provider_error() -> None:
    client = MagicMock()
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "HeadObject",
    )

    with pytest.raises(ClientError):
        _store(client).stat("restricted.bin")
