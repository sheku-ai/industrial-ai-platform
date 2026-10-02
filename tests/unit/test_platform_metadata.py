from app.core.config import Settings
from app.core.platform_metadata import (
    CURRENT_SPRINT,
    CURRENT_WORK_PACKAGE,
    PRODUCT_VERSION,
    RELEASE_STAGE,
    build_platform_info,
)
from app.schemas.product_api import ProductApiStatus


def test_platform_metadata_is_canonical() -> None:
    info = build_platform_info(Settings())
    assert PRODUCT_VERSION == "1.6.0"
    assert CURRENT_WORK_PACKAGE == "1.6.0"
    assert info.release_stage == "pre-production"
    assert info.current_objective == "SHEKU 1.6.0 release candidate preparation"
    assert info.product_version == PRODUCT_VERSION
    assert info.current_sprint == CURRENT_SPRINT
    assert info.current_work_package == CURRENT_WORK_PACKAGE
    assert info.provider_execution_enabled is False


def test_product_api_status_matches_canonical_metadata_and_response_shape() -> None:
    assert ProductApiStatus().model_dump() == {
        "version": PRODUCT_VERSION,
        "sprint": CURRENT_SPRINT,
        "work_package": CURRENT_WORK_PACKAGE,
        "status": RELEASE_STAGE,
    }
