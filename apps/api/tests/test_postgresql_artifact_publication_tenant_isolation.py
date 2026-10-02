from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from app.services.artifact_publication_retry import ArtifactPublicationRetryService
from tests.integration_support.postgresql_fixtures import (
    create_integration_organization,
    delete_integration_organization,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="explicit PostgreSQL integration environment is required",
)


def test_publication_retry_does_not_cross_organization_boundary():
    assert DATABASE_URL is not None

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    organization_a = uuid4()
    organization_b = uuid4()
    execution_a = uuid4()
    execution_b = uuid4()
    artifact_a = uuid4()
    artifact_b = uuid4()
    storage_uri = f"s3://integration/{uuid4()}/tenant-isolation/object.json"
    checksum = "b" * 64

    try:
        create_integration_organization(session, organization_id=organization_a, label="integration-a")
        create_integration_organization(session, organization_id=organization_b, label="integration-b")
        session.add_all(
            [
                RuntimeExecution(
                    id=execution_a,
                    organization_id=organization_a,
                    execution_type="integration.validation",
                    subject_type="integration.fixture",
                    subject_id=uuid4(),
                    status="pending",
                    input_payload={},
                    policy_snapshot={},
                    metrics={},
                ),
                RuntimeExecution(
                    id=execution_b,
                    organization_id=organization_b,
                    execution_type="integration.validation",
                    subject_type="integration.fixture",
                    subject_id=uuid4(),
                    status="pending",
                    input_payload={},
                    policy_snapshot={},
                    metrics={},
                ),
                RuntimeExecutionArtifact(
                    id=artifact_a,
                    organization_id=organization_a,
                    execution_id=execution_a,
                    attempt_id=None,
                    artifact_type="integration.manifest",
                    storage_uri=storage_uri,
                    media_type="application/json",
                    checksum_sha256=checksum,
                    size_bytes=10,
                    metadata_={},
                    status="registered",
                ),
                RuntimeExecutionArtifact(
                    id=artifact_b,
                    organization_id=organization_b,
                    execution_id=execution_b,
                    attempt_id=None,
                    artifact_type="integration.manifest",
                    storage_uri=storage_uri,
                    media_type="application/json",
                    checksum_sha256=checksum,
                    size_bytes=10,
                    metadata_={},
                    status="registered",
                ),
            ]
        )
        session.flush()

        lifecycle = ArtifactPublicationLifecycleService(session)
        publication_a = lifecycle.reserve(
            organization_id=organization_a,
            execution_id=execution_a,
            artifact_id=artifact_a,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=10,
        )
        lifecycle.mark_publishing(organization_a, publication_a.id)
        lifecycle.mark_published(organization_a, publication_a.id)
        lifecycle.mark_verified(organization_a, publication_a.id)
        session.commit()

        result_b = ArtifactPublicationRetryService(lifecycle).resolve_or_reserve(
            organization_id=organization_b,
            execution_id=execution_b,
            artifact_id=artifact_b,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=10,
        )
        session.commit()

        assert result_b.reused is False
        assert result_b.publication_id != publication_a.id
    finally:
        session.rollback()
        for execution_id in (execution_a, execution_b):
            execution = session.get(RuntimeExecution, execution_id)
            if execution is not None:
                session.delete(execution)
        session.flush()
        delete_integration_organization(session, organization_a)
        delete_integration_organization(session, organization_b)
        session.commit()
        session.close()
        engine.dispose()
