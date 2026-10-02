from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.product_integration import ProductIntegrationRuntimeResponse
from app.services.product_integration_runtime import build_product_integration_runtime

router = APIRouter(prefix="/platform/product/integration", tags=["product-integration"])


@router.get("/runtime", response_model=ProductIntegrationRuntimeResponse)
def get_product_integration_runtime(db: Session = Depends(get_db)):
    return build_product_integration_runtime(db)
