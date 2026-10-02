from hashlib import sha256
from uuid import UUID

import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.core.config import get_settings
from app.db.session import get_db
from app.models.documents import DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.schemas.document_ingestion import (
    DocumentIngestionRequest,
    DocumentIngestionRequestResponse,
    DocumentVersionUploadConfirmResponse,
    DocumentVersionUploadRequest,
    DocumentVersionUploadResponse,
)
from app.services.ingestion_contracts import IngestionContractError
from app.services.object_storage_upload import S3CompatibleUploadService
from app.services.runtime_lifecycle import RuntimeLifecycleService

router = APIRouter(prefix="/documents", tags=["document-ingestion"])


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} was not found")


def _upload_service() -> S3CompatibleUploadService:
    settings = get_settings()
    if not settings.object_storage_bucket:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="object storage is not configured")
    client = boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url or None,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key or None,
        aws_secret_access_key=settings.object_storage_secret_key or None,
        use_ssl=settings.object_storage_secure,
    )
    return S3CompatibleUploadService(client, bucket=settings.object_storage_bucket)


@router.post(
    "/{document_id}/versions/uploads",
    response_model=DocumentVersionUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document_version_upload(
    document_id: UUID,
    payload: DocumentVersionUploadRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> DocumentVersionUploadResponse:
    document = db.scalar(
        select(DocumentRecord)
        .where(
            DocumentRecord.id == document_id,
            DocumentRecord.organization_id == context.organization_id,
        )
        .with_for_update()
    )
    if document is None:
        raise _not_found("document")

    next_version = (
        int(
            db.scalar(
                select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                    DocumentVersion.document_record_id == document.id
                )
            )
            or 0
        )
        + 1
    )
    version = DocumentVersion(
        organization_id=context.organization_id,
        document_record_id=document.id,
        version_number=next_version,
        version_label=payload.version_label,
        content_type=payload.content_type,
        file_name=payload.file_name,
        size_bytes=payload.size_bytes,
        checksum_sha256=payload.checksum_sha256.lower(),
        object_store_provider="s3-compatible",
        object_store_bucket=get_settings().object_storage_bucket,
        object_store_key="pending",
        source_snapshot={"upload_contract": "presigned_put_v1"},
        status="upload_pending",
        created_by=context.actor_reference,
        updated_by=context.actor_reference,
    )
    try:
        db.add(version)
        db.flush()
        upload = _upload_service().create_upload(
            context.organization_id,
            document.id,
            version.id,
            file_name=payload.file_name,
            content_type=payload.content_type,
            checksum_sha256=payload.checksum_sha256,
        )
        version.object_store_bucket = upload.bucket
        version.object_store_key = upload.key
        version.source_snapshot = {
            "upload_contract": "presigned_put_v1",
            "required_headers": dict(upload.required_headers),
        }
        db.commit()
    except IngestionContractError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return DocumentVersionUploadResponse(
        organization_id=context.organization_id,
        document_id=document.id,
        document_version_id=version.id,
        version_number=version.version_number,
        status=version.status,
        bucket=upload.bucket,
        object_key=upload.key,
        upload_url=upload.url,
        method=upload.method,
        required_headers=upload.required_headers,
        expires_in_seconds=upload.expires_in_seconds,
    )


@router.post(
    "/versions/{document_version_id}/uploads/confirm",
    response_model=DocumentVersionUploadConfirmResponse,
)
def confirm_document_version_upload(
    document_version_id: UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> DocumentVersionUploadConfirmResponse:
    version = db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == document_version_id,
            DocumentVersion.organization_id == context.organization_id,
        )
        .with_for_update()
    )
    if version is None:
        raise _not_found("document version")
    if version.status != "upload_pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document version is not awaiting upload confirmation"
        )
    if not version.object_store_bucket or not version.object_store_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document version has no upload location")

    try:
        stored = _upload_service().verify_upload(
            bucket=version.object_store_bucket,
            key=version.object_store_key,
        )
    except IngestionContractError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if stored.content_length != version.size_bytes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="uploaded object size does not match document version"
        )
    if stored.checksum_sha256 != version.checksum_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="uploaded object checksum does not match document version"
        )
    if stored.content_type != version.content_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="uploaded object content type does not match document version"
        )

    version.status = "registered"
    version.source_snapshot = {
        **dict(version.source_snapshot or {}),
        "upload_confirmed": True,
        "source_reference": f"s3://{stored.bucket}/{stored.key}",
    }
    version.updated_by = context.actor_reference
    db.commit()

    return DocumentVersionUploadConfirmResponse(
        organization_id=context.organization_id,
        document_id=version.document_record_id,
        document_version_id=version.id,
        version_number=version.version_number,
        status=version.status,
        content_type=version.content_type,
        size_bytes=version.size_bytes,
        checksum_sha256=version.checksum_sha256,
    )


@router.post(
    "/versions/{document_version_id}/ingestion-executions",
    response_model=DocumentIngestionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_document_ingestion(
    document_version_id: UUID,
    payload: DocumentIngestionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> DocumentIngestionRequestResponse:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == document_version_id, DocumentVersion.organization_id == context.organization_id
        )
    )
    if version is None:
        raise _not_found("document version")
    if version.status != "registered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document version source upload is not confirmed"
        )

    document = db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.id == version.document_record_id, DocumentRecord.organization_id == context.organization_id
        )
    )
    if document is None:
        raise _not_found("document")
    profile = db.scalar(
        select(IngestionPipelineProfile).where(
            IngestionPipelineProfile.id == payload.pipeline_profile_id,
            IngestionPipelineProfile.organization_id == context.organization_id,
            IngestionPipelineProfile.enabled.is_(True),
        )
    )
    if profile is None:
        raise _not_found("ingestion pipeline profile")
    if not version.object_store_bucket or not version.object_store_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document version does not reference a stored source object"
        )
    if not version.file_name or not version.content_type or version.size_bytes is None or not version.checksum_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document version source metadata is incomplete"
        )

    source_reference = f"s3://{version.object_store_bucket}/{version.object_store_key}"
    identity = ":".join(
        [str(context.organization_id), str(version.id), str(profile.id), profile.revision, version.checksum_sha256]
    )
    idempotency_key = f"document.ingestion:{sha256(identity.encode('utf-8')).hexdigest()}"
    execution, created = RuntimeLifecycleService(db).create_or_get(
        organization_id=context.organization_id,
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=version.id,
        idempotency_key=idempotency_key,
        requested_by=context.actor_reference,
        correlation_id=payload.correlation_id or context.correlation_id,
        priority=payload.priority,
        input_payload={
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "source_reference": source_reference,
            "declared_media_type": version.content_type,
            "original_file_name": version.file_name,
            "content_length": version.size_bytes,
            "checksum_sha256": version.checksum_sha256,
            "pipeline_profile_id": str(profile.id),
            "adapter_hint": payload.adapter_hint,
            "metadata_template_id": str(document.metadata_template_id) if document.metadata_template_id else None,
            "metadata": dict(payload.metadata),
            "options": dict(payload.options),
        },
        policy_snapshot={
            "pipeline_profile_id": str(profile.id),
            "pipeline_profile_revision": profile.revision,
            "deployment_edition": profile.deployment_edition,
        },
    )
    db.commit()
    return DocumentIngestionRequestResponse(
        execution_id=execution.id,
        organization_id=execution.organization_id,
        document_id=document.id,
        document_version_id=version.id,
        pipeline_profile_id=profile.id,
        status=execution.status,
        created=created,
        requested_at=execution.requested_at,
        source_reference=source_reference,
    )
