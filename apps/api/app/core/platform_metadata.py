from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReleaseStage = Literal["development", "pre-production", "production"]

PRODUCT_NAME = "SHEKU"
PRODUCT_VERSION = "1.6.0"
RELEASE_STAGE: ReleaseStage = "pre-production"
CURRENT_SPRINT = "release"
CURRENT_WORK_PACKAGE = "1.6.0"
CURRENT_OBJECTIVE = "SHEKU 1.6.0 release candidate preparation"
PROVIDER_EXECUTION_ENABLED = False


class PlatformBuildInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    product_name: str = PRODUCT_NAME
    product_version: str = PRODUCT_VERSION
    release_stage: ReleaseStage = RELEASE_STAGE
    current_sprint: str = CURRENT_SPRINT
    current_work_package: str = CURRENT_WORK_PACKAGE
    current_objective: str = CURRENT_OBJECTIVE
    build_commit: str = "unknown"
    build_timestamp: datetime | None = None
    database_revision: str = "unknown"
    configuration_revision: str = "unknown"
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    provider_execution_enabled: bool = PROVIDER_EXECUTION_ENABLED
    no_ai_ready: bool = True

    @field_validator("provider_execution_enabled")
    @classmethod
    def provider_execution_must_remain_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("provider execution must remain disabled")
        return value


def build_platform_info(settings: Any) -> PlatformBuildInfo:
    return PlatformBuildInfo(
        build_commit=getattr(settings, "build_commit", "unknown") or "unknown",
        build_timestamp=getattr(settings, "build_timestamp", None),
        database_revision=getattr(settings, "database_revision", "unknown") or "unknown",
        configuration_revision=getattr(settings, "configuration_revision", "unknown") or "unknown",
        feature_flags={
            "ai_provider_execution": False,
            "embeddings": bool(getattr(settings, "feature_embeddings_enabled", False)),
            "vector_retrieval": bool(getattr(settings, "feature_vector_retrieval_enabled", False)),
            "worker": bool(getattr(settings, "feature_worker_enabled", False)),
            "enterprise_extensions": bool(getattr(settings, "feature_enterprise_extensions_enabled", False)),
        },
        provider_execution_enabled=False,
    )
