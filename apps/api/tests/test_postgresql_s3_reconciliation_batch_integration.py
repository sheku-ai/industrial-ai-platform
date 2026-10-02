from __future__ import annotations

import os
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.infrastructure.s3_artifact_object_store import S3ArtifactObjectStore
from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from app.services.artifact_reconciliation_batch import ArtifactReconciliationBatchService
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


def test_reconciliation_batch_previews_then_verifies_latest_publication():
    assert DATABASE_URL is not None
    assert S3_ENVIRONMENT is not None

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    setup_session = Session()
    write_store = S3CompatibleObjectStore(
        endpoint_url=S3_ENVIRONMENT.endpoint_url,
        access_key_id=S3_ENVIRONMENT.access_key_id,
        secret_access_key=S3_ENVIRONMENT.secret_access_key,
        bucket=S3_ENVIRONMENT.bucket,
        region=S3_ENVIRONMENT.region,
        use_ssl=S3_ENVIRONMENT.use_ssl,
    )
    read_store = S3ArtifactObjectStore(
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
    key = f"integration/{run_id}/reconciliation-batch/item.json"
    storage_uri = f"s3://{S3_ENVIRONMENT.bucket}/{key}"
    payload = b'{"integration":true,"kind":"reconciliation-batch"}'
    checksum = sha256(payload).hexdigest()

    try:
        create_integration_organization(setup_session, organization_id=organization_id)
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
            artifact_type="integration.reconciliation",
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=len(payload),
            metadata_={"validation_run_id": str(run_id)},
            status="registered",
        )
        setup_session.add_all([execution, artifact])
        setup_session.flush()

        lifecycle = ArtifactPublicationLifecycleService(setup_session)
        publication = lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=checksum,
            size_bytes=len(payload),
            metadata={"validation_run_id": str(run_id)},
        )
        lifecycle.mark_publishing(organization_id, publication.id)
        write_store.put_bytes(key, payload, content_type="application/json")
        lifecycle.mark_published(organization_id, publication.id)
        setup_session.commit()

        service = ArtifactReconciliationBatchService(Session, read_store)
        preview = service.run(
            organization_id,
            limit=10,
            statuses=["published"],
            dry_run=True,
        )
        assert preview.scanned == 1
        assert preview.processed == 1
        assert preview.verified == 1
        assert preview.changed == 1

        after_preview = setup_session.scalar(
            select(RuntimeArtifactPublication).where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.id == publication.id,
            )
        )
        setup_session.refresh(after_preview)
        assert after_preview is not None
        assert after_preview.status == "published"

        result = service.run(
            organization_id,
            limit=10,
            statuses=["published"],
            dry_run=False,
        )
        assert result.scanned == 1
        assert result.processed == 1
        assert result.verified == 1
        assert result.changed == 1

        setup_session.expire_all()
        persisted = setup_session.scalar(
            select(RuntimeArtifactPublication).where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.id == publication.id,
            )
        )
        assert persisted is not None
        assert persisted.status == "verified"
    finally:
        setup_session.rollback()
        try:
            write_store.remove(key)
        finally:
            execution = setup_session.get(RuntimeExecution, execution_id)
            if execution is not None:
                setup_session.delete(execution)
                setup_session.flush()
            delete_integration_organization(setup_session, organization_id)
            setup_session.commit()
            setup_session.close()
            engine.dispose()
