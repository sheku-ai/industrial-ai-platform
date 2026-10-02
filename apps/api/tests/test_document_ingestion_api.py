from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.identity.db import get_identity_db
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def configured_identity_dependency():
    def _identity_db():
        yield object()

    app.dependency_overrides[get_identity_db] = _identity_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_identity_db, None)


def test_document_ingestion_and_upload_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/api/documents/versions/{document_version_id}/ingestion-executions" in paths
    assert "/api/documents/{document_id}/versions/uploads" in paths
    assert "/api/documents/versions/{document_version_id}/uploads/confirm" in paths


def test_document_ingestion_request_does_not_accept_tenant_or_source_reference():
    schema = app.openapi()["components"]["schemas"]["DocumentIngestionRequest"]
    properties = schema["properties"]

    assert "organization_id" not in properties
    assert "source_reference" not in properties
    assert "document_id" not in properties
    assert "document_version_id" not in properties
    assert "pipeline_profile_id" in schema["required"]


def test_upload_request_does_not_accept_storage_location_or_tenant():
    schema = app.openapi()["components"]["schemas"]["DocumentVersionUploadRequest"]
    properties = schema["properties"]

    assert "organization_id" not in properties
    assert "bucket" not in properties
    assert "object_key" not in properties
    assert "object_store_provider" not in properties
    assert set(schema["required"]) >= {"file_name", "content_type", "size_bytes", "checksum_sha256"}


def test_document_ingestion_requires_authentication_before_tenant_context():
    response = client.post(
        f"/api/documents/versions/{uuid4()}/ingestion-executions",
        json={"pipeline_profile_id": str(uuid4())},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication_required"


def test_document_upload_requires_authentication_before_tenant_context():
    response = client.post(
        f"/api/documents/{uuid4()}/versions/uploads",
        json={
            "file_name": "source.txt",
            "content_type": "text/plain",
            "size_bytes": 4,
            "checksum_sha256": "a" * 64,
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication_required"


def test_legacy_organization_header_does_not_bypass_document_authentication():
    response = client.post(
        "/api/documents/versions/not-a-uuid/ingestion-executions",
        headers={"X-Organization-ID": str(uuid4())},
        json={"pipeline_profile_id": str(uuid4())},
    )

    assert response.status_code == 401


def test_upload_confirmation_requires_authentication():
    response = client.post(
        "/api/documents/versions/not-a-uuid/uploads/confirm",
        headers={"X-Organization-ID": str(uuid4())},
    )

    assert response.status_code == 401
