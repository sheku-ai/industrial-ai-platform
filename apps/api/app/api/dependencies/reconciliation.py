from fastapi import HTTPException, status

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.infrastructure.s3_artifact_object_store import S3ArtifactObjectStore
from app.services.artifact_reconciliation_batch import ArtifactReconciliationBatchService


def get_reconciliation_batch_service() -> ArtifactReconciliationBatchService:
    if SessionLocal is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )

    settings = get_settings()
    required = (
        settings.object_storage_endpoint_url,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_bucket,
    )
    if not all(value.strip() for value in required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="object storage is not configured",
        )

    object_store = S3ArtifactObjectStore(
        endpoint_url=settings.object_storage_endpoint_url,
        access_key_id=settings.object_storage_access_key,
        secret_access_key=settings.object_storage_secret_key,
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
        use_ssl=settings.object_storage_secure,
    )
    return ArtifactReconciliationBatchService(SessionLocal, object_store)
