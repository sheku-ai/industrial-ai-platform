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
from app.services.artifact_reconciliation import ArtifactReconciliationService
from tests.integration_support.postgresql_fixtures import (
    create_integration_organization,
    delete_integration_organization,
)
from tests.integration_support.s3_artifact_store import S3ArtifactObjectStoreAdapter
from tests.integration_support.s3_environment import load_s3_integration_environment
from tests.integration_support.s3_object_store import S3CompatibleObjectStore

DATABASE_URL = os.getenv("DATABASE_URL")
S3_ENVIRONMENT = load_s3_integration_environment()
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or S3_ENVIRONMENT is None,
    reason="explicit PostgreSQL and S3 integration environments are required",
)


def test_published_registry_record_without_object_creates_one_missing_finding():
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
    artifact_store = S3ArtifactObjectStoreAdapter(store, bucket=S3_ENVIRONMENT.bucket)
    organization_id = uuid4()
    execution_id = uuid4()
    artifact_id = uuid4()
    run_id = uuid4()
    key = f"integration/{run_id}/missing-object/manifest.json"
    storage_uri = f"s3://{S3_ENVIRONMENT.bucket}/{key}"
    expected_payload = b'{"expected":true,"object":"missing"}'
    expected_checksum = sha256(expected_payload).hexdigest()
    try:
        store.remove(key)
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
            checksum_sha256=expected_checksum,
            size_bytes=len(expected_payload),
            metadata_={"validation_run_id": str(run_id)},
            status="registered",
        )
        session.add_all([execution, artifact])
        session.flush()
        lifecycle = ArtifactPublicationLifecycleService(session)
        source = lifecycle.reserve(
            organization_id=organization_id,
            execution_id=execution_id,
            artifact_id=artifact_id,
            attempt_id=None,
            storage_uri=storage_uri,
            media_type="application/json",
            checksum_sha256=expected_checksum,
            size_bytes=len(expected_payload),
            metadata={"validation_run_id": str(run_id)},
        )
        lifecycle.mark_publishing(organization_id, source.id)
        lifecycle.mark_published(organization_id, source.id)
        session.commit()
        reconciliation = ArtifactReconciliationService(lifecycle, artifact_store)
        first = reconciliation.reconcile(organization_id, source.id)
        session.commit()
        assert first.outcome == "missing"
        assert first.changed is True
        assert first.resulting_publication_id != source.id
        publications = list(
            session.scalars(
                select(RuntimeArtifactPublication)
                .where(RuntimeArtifactPublication.artifact_id == artifact_id)
                .order_by(RuntimeArtifactPublication.publication_number)
            )
        )
        assert len(publications) == 2
        assert publications[0].id == source.id
        assert publications[0].status == "published"
        assert publications[1].id == first.resulting_publication_id
        assert publications[1].status == "missing"
        assert publications[1].metadata_["reconciliation_of"] == str(source.id)
        second = reconciliation.reconcile(organization_id, publications[1].id)
        session.commit()
        assert second.outcome == "missing"
        assert second.changed is False
        assert second.resulting_publication_id == publications[1].id
        assert (
            len(
                list(
                    session.scalars(
                        select(RuntimeArtifactPublication).where(RuntimeArtifactPublication.artifact_id == artifact_id)
                    )
                )
            )
            == 2
        )
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
