from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.reconciliation import get_reconciliation_batch_service
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.schemas.reconciliation_api import (
    ReconciliationBatchItemRead,
    ReconciliationBatchRequest,
    ReconciliationBatchResponse,
)
from app.services.artifact_reconciliation_batch import (
    ArtifactReconciliationBatchError,
    ArtifactReconciliationBatchService,
)

router = APIRouter(prefix="/control-plane/reconciliation/artifacts", tags=["control-plane-reconciliation"])


def _to_response(mode: str, result) -> ReconciliationBatchResponse:
    return ReconciliationBatchResponse(
        mode=mode,
        scanned=result.scanned,
        processed=result.processed,
        changed=result.changed,
        verified=result.verified,
        missing=result.missing,
        checksum_conflict=result.checksum_conflict,
        unchanged=result.unchanged,
        failed=result.failed,
        next_cursor=result.next_cursor,
        items=tuple(
            ReconciliationBatchItemRead(
                source_publication_id=item.source_publication_id,
                resulting_publication_id=item.resulting_publication_id,
                outcome=item.outcome,
                changed=item.changed,
                error_code=item.error_code,
            )
            for item in result.items
        ),
    )


def _run(
    payload: ReconciliationBatchRequest,
    *,
    context: RuntimeRequestContext,
    service: ArtifactReconciliationBatchService,
    dry_run: bool,
) -> ReconciliationBatchResponse:
    try:
        result = service.run(
            context.organization_id,
            limit=payload.limit,
            statuses=payload.statuses,
            cursor=payload.cursor,
            dry_run=dry_run,
        )
    except ArtifactReconciliationBatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return _to_response("preview" if dry_run else "run", result)


def _record_run_event(
    db: Session,
    *,
    context: RuntimeRequestContext,
    payload: ReconciliationBatchRequest,
    response: ReconciliationBatchResponse,
) -> None:
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_type="user" if context.actor_reference else "system",
            actor_id=context.actor_reference,
            resource_type="artifact_publication_reconciliation",
            resource_id=payload.correlation_id,
            summary="artifact publication reconciliation run",
            metadata_json={
                "mode": response.mode,
                "limit": payload.limit,
                "statuses": payload.statuses or [],
                "correlation_id": payload.correlation_id,
                "scanned": response.scanned,
                "processed": response.processed,
                "changed": response.changed,
                "failed": response.failed,
            },
        )
    )
    db.commit()


@router.post("/preview", response_model=ReconciliationBatchResponse)
def preview_artifact_reconciliation(
    payload: ReconciliationBatchRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    service: ArtifactReconciliationBatchService = Depends(get_reconciliation_batch_service),
) -> ReconciliationBatchResponse:
    if not context.has_permission("control_plane.reconciliation", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="reconciliation read permission is required",
        )
    return _run(payload, context=context, service=service, dry_run=True)


@router.post("/run", response_model=ReconciliationBatchResponse)
def run_artifact_reconciliation(
    payload: ReconciliationBatchRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    service: ArtifactReconciliationBatchService = Depends(get_reconciliation_batch_service),
    db: Session = Depends(get_db),
) -> ReconciliationBatchResponse:
    if not context.has_permission("control_plane.reconciliation", "administer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="reconciliation administration permission is required",
        )
    response = _run(payload, context=context, service=service, dry_run=False)
    _record_run_event(db, context=context, payload=payload, response=response)
    return response
