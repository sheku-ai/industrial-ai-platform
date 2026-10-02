from __future__ import annotations

import os
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from tests.integration_support.postgresql_fixtures import (
    create_integration_organization,
    delete_integration_organization,
)
from tests.integration_support.s3_environment import load_s3_integration_environment
from tests.integration_support.s3_object_store import S3CompatibleObjectStore

DATABASE_URL = os.getenv("DATABASE_URL")
S3_ENVIRONMENT = load_s3_integration_environment()
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or S3_ENVIRONMENT is None,
    reason="explicit PostgreSQL and S3 integration environments are required",
)


def test_postgresql_registry_and_s3_object_reach_verified_state():
    assert DATABASE_URL is not None
    assert S3_ENVIRONMENT is not None

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    store = S3CompatibleObjectStore(
        endpoint_url=S3_ENVIRONMENT.endpoint_url,
        access_key_id=S3_ENVIRONMENT.access_key_id,
        secret_access_key=S3_ENVIRONMENT.secret_access_key,
        bucket=S3_ENVIRONMENT.bucket,
        region=S3_ENVIRONMENT.region,
        use_ssl=S3_ENVIRONMENT.use_ssl,
    )

    organization_id = uuid4()
    execution_id = uuid4()
    artifact_id = uuid4()
    run_id = uuid4()
    key = f"integration/{run_id}/artifact-publication/manifest.json"
    storage_uri = f"s3://{S3_ENVIRONMENT.bucket}/{key}"
    payload = b'{"integration":true,"kind":"artifact-publication"}'
    expected_checksum = sha256(payload).hexdigest()

    try:
        create_integration_organization(session, organization_id=organization_id)
        execution = RuntimeExecution(
            id=execution_id,
            organization_id=organization_id,
            execution_type="integration.validation",
            subject_type="integration.fixture",
            subject_id=uuid4(),
            status="pending",
            input_payload={"validation_run_id": str(run_id)},
            policy_snapshot={},
            metrics={},
        )
        artifact = RuntimeExecutionArtifact(
            id=artifact_id,
            organization_id=organization_id,
            execution_id=execution_id,
            attempt_id=None,
            artifact_type="integration.manifest",
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=None,
            size_bytes=None,
            metadata_={"validation_run_id": str(run_id)},
            status="registered",
        )
        session.add_all([execution, artifact])
        session.flush()

        lifecycle = ArtifactPublicationLifecycleService(session)
        publication = lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=expected_checksum,
            size_bytes=len(payload),
            metadata={"validation_run_id": str(run_id)},
        )
        lifecycle.mark_publishing(organization_id, publication.id)

        stored_checksum = store.put_bytes(key, payload, content_type="application/json")
        metadata = store.stat(key)
        assert metadata is not None
        assert stored_checksum == expected_checksum
        assert metadata.checksum_sha256 == expected_checksum
        assert metadata.size_bytes == len(payload)

        lifecycle.mark_published(organization_id, publication.id)
        lifecycle.mark_verified(organization_id, publication.id)
        session.commit()

        persisted = session.scalar(
            select(RuntimeArtifactPublication).where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.id == publication.id,
            )
        )
        assert persisted is not None
        assert persisted.status == "verified"
        assert persisted.publication_number == 1
        assert persisted.storage_uri == storage_uri
        assert persisted.checksum_sha256 == expected_checksum
        assert persisted.size_bytes == len(payload)
        assert persisted.published_at is not None
        assert persisted.verified_at is not None
        assert store.read_bytes(key) == payload
    finally:
        session.rollback()
        try:
            store.remove(key)
        finally:
            execution = session.get(RuntimeExecution, execution_id)
            if execution is not None:
                session.delete(execution)
                session.flush()
            delete_integration_organization(session, organization_id)
            session.commit()
            session.close()
            engine.dispose()
