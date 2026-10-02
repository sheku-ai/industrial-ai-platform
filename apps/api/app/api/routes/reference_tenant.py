from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.reference_tenant import (
    ReferenceTenantInventory,
    ReferenceTenantProvisionRequest,
    ReferenceTenantProvisionResponse,
    ReferenceTenantReadiness,
    ReferenceTenantStatus,
    ReferenceTenantValidationResponse,
)
from app.services.reference_tenant import (
    build_reference_tenant_assets,
    build_reference_tenant_readiness,
    build_reference_tenant_status,
    provision_reference_tenant,
    validate_reference_tenant,
)

router = APIRouter(prefix="/reference-tenant", tags=["reference-tenant"])


@router.get("/readiness", response_model=ReferenceTenantReadiness)
def readiness(db: Session = Depends(get_db)):
    return build_reference_tenant_readiness(db)


@router.post("/provision", response_model=ReferenceTenantProvisionResponse)
def provision(payload: ReferenceTenantProvisionRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or ReferenceTenantProvisionRequest()
    return provision_reference_tenant(db, requested_by=payload.requested_by)


@router.get("/status", response_model=ReferenceTenantStatus)
def status(db: Session = Depends(get_db)):
    return build_reference_tenant_status(db)


@router.get("/assets", response_model=ReferenceTenantInventory)
def assets(db: Session = Depends(get_db)):
    return build_reference_tenant_assets(db)


@router.post("/validate", response_model=ReferenceTenantValidationResponse)
def validate(db: Session = Depends(get_db)):
    return validate_reference_tenant(db)
