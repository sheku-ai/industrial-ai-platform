from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DatabaseConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    driver: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None


class ObjectStorageConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    endpoint_host: str | None = None
    endpoint_port: int | None = None
    secure: bool
    region: str
    bucket_configured: bool
    credentials_configured: bool


class IngestionConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_root: str
    max_source_bytes: int
    worker_enabled: bool


class OperationalHealthConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    pending_warning_seconds: int
    stale_data_seconds: int
    failed_run_critical_count: int


class EffectivePlatformConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str
    app_version: str
    portal_port: int
    cors_origins: list[str]
    database: DatabaseConfiguration
    object_storage: ObjectStorageConfiguration
    ingestion: IngestionConfiguration
    operational_health: OperationalHealthConfiguration
    feature_flags: dict[str, bool]
    build_commit: str
    database_revision: str
    configuration_revision: str
    provider_execution_enabled: bool = False
