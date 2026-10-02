from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.artifact_publication import RuntimeArtifactPublication
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


def test_same_checksum_retry_reuses_verified_publication():
    assert DATABASE_URL is not None

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    organization_id = uuid4()
    execution_id = uuid4()
    artifact_id = uuid4()
    storage_uri = f"s3://integration/{uuid4()}/same-checksum/object.json"
    checksum = "a" * 64

    try:
        create_integration_organization(session, organization_id=organization_id)
        execution = RuntimeExecution(
            id=execution_id,
            organization_id=organization_id,
            execution_type="integration.validation",
            subject_type="integration.fixture",
            subject_id=uuid4(),
            status="pending",
            input_payload={},
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
            checksum_sha256=checksum,
            size_bytes=10,
            metadata_={},
            status="registered",
        )
        session.add_all([execution, artifact])
        session.flush()

        lifecycle = ArtifactPublicationLifecycleService(session)
        first = lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=10,
        )
        lifecycle.mark_publishing(organization_id, first.id)
        lifecycle.mark_published(organization_id, first.id)
        lifecycle.mark_verified(organization_id, first.id)
        session.commit()

        retry = ArtifactPublicationRetryService(lifecycle).resolve_or_reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=10,
            metadata={"retry": True},
        )
        session.commit()

        assert retry.reused is True
        assert retry.publication_id == first.id
        assert len(
            list(
                session.scalars(
                    select(RuntimeArtifactPublication).where(
                        RuntimeArtifactPublication.artifact_id == artifact_id
                    )
                )
            )
        ) == 1
    finally:
        session.rollback()
        execution = session.get(RuntimeExecution, execution_id)
        if execution is not None:
            session.delete(execution)
            session.flush()
        delete_integration_organization(session, organization_id)
        session.commit()
        session.close()
        engine.dispose()
