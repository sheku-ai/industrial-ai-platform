from uuid import uuid4

import pytest

from app.services.ingestion_contracts import IngestionContractError
from app.services.object_storage_upload import S3CompatibleUploadService


class Client:
    def __init__(self):
        self.presign = None

    def generate_presigned_url(self, operation, Params, ExpiresIn, HttpMethod):
        self.presign = (operation, Params, ExpiresIn, HttpMethod)
        return "https://storage.example/upload"

    def head_object(self, **kwargs):
        return {
            "ContentLength": 4,
            "ContentType": "text/plain",
            "Metadata": {"sha256": "a" * 64},
        }


def test_creates_tenant_scoped_presigned_upload():
    organization_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    client = Client()
    service = S3CompatibleUploadService(client, bucket="documents", expires_in_seconds=600)

    upload = service.create_upload(
        organization_id,
        document_id,
        version_id,
        file_name="source file.txt",
        content_type="text/plain",
        checksum_sha256="a" * 64,
    )

    assert upload.key == f"{organization_id}/{document_id}/{version_id}/source_file.txt"
    assert upload.required_headers["x-amz-meta-sha256"] == "a" * 64
    assert client.presign[0] == "put_object"
    assert client.presign[3] == "PUT"


def test_verifies_uploaded_object_metadata():
    service = S3CompatibleUploadService(Client(), bucket="documents")
    stored = service.verify_upload(bucket="documents", key="tenant/document/version/source.txt")

    assert stored.content_length == 4
    assert stored.content_type == "text/plain"
    assert stored.checksum_sha256 == "a" * 64


def test_rejects_invalid_checksum_before_presigning():
    service = S3CompatibleUploadService(Client(), bucket="documents")
    with pytest.raises(IngestionContractError, match="SHA-256"):
        service.create_upload(
            uuid4(),
            uuid4(),
            uuid4(),
            file_name="source.txt",
            content_type="text/plain",
            checksum_sha256="invalid",
        )


def test_rejects_verification_in_other_bucket():
    service = S3CompatibleUploadService(Client(), bucket="documents")
    with pytest.raises(IngestionContractError, match="not allowed"):
        service.verify_upload(bucket="other", key="source.txt")
