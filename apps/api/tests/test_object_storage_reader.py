from io import BytesIO
from uuid import uuid4

import pytest

from app.services.ingestion_contracts import IngestionContractError
from app.services.object_storage_reader import S3CompatibleSourceObjectReader


class Client:
    def __init__(self):
        self.calls = []

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return {
            "ContentLength": 4,
            "ContentType": "text/plain",
            "Metadata": {"sha256": "a" * 64},
        }

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"Body": BytesIO(b"test")}


def test_reads_object_inside_organization_namespace():
    organization_id = uuid4()
    client = Client()
    reader = S3CompatibleSourceObjectReader(client, required_bucket="documents")
    reference = f"s3://documents/{organization_id}/source.txt"

    descriptor = reader.describe(organization_id, reference)
    stream = reader.open_stream(organization_id, reference)

    assert descriptor.file_name == "source.txt"
    assert descriptor.content_length == 4
    assert descriptor.checksum_sha256 == "a" * 64
    assert stream.read() == b"test"


def test_rejects_cross_organization_object():
    reader = S3CompatibleSourceObjectReader(Client(), required_bucket="documents")
    with pytest.raises(IngestionContractError, match="organization namespace"):
        reader.describe(uuid4(), f"s3://documents/{uuid4()}/source.txt")


def test_rejects_unconfigured_bucket():
    organization_id = uuid4()
    reader = S3CompatibleSourceObjectReader(Client(), required_bucket="documents")
    with pytest.raises(IngestionContractError, match="bucket is not allowed"):
        reader.describe(organization_id, f"s3://other/{organization_id}/source.txt")


def test_requires_sha256_object_metadata():
    class MissingChecksum(Client):
        def head_object(self, **kwargs):
            return {"ContentLength": 4, "ContentType": "text/plain", "Metadata": {}}

    organization_id = uuid4()
    reader = S3CompatibleSourceObjectReader(MissingChecksum())
    with pytest.raises(IngestionContractError, match="missing sha256 metadata"):
        reader.describe(organization_id, f"s3://documents/{organization_id}/source.txt")
