from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from app.schemas.effective_configuration import (
    DatabaseConfiguration,
    EffectivePlatformConfiguration,
    IngestionConfiguration,
    ObjectStorageConfiguration,
    OperationalHealthConfiguration,
)


def _database_configuration(database_url: str) -> DatabaseConfiguration:
    if not database_url.strip():
        return DatabaseConfiguration(configured=False)

    try:
        parsed = make_url(database_url)
    except Exception:
        return DatabaseConfiguration(configured=True)

    return DatabaseConfiguration(
        configured=True,
        driver=parsed.drivername,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )


def _object_storage_configuration(settings: Any) -> ObjectStorageConfiguration:
    endpoint = str(getattr(settings, "object_storage_endpoint_url", "") or "").strip()
    parsed = urlparse(endpoint) if endpoint else None
    access_key = str(getattr(settings, "object_storage_access_key", "") or "")
    secret_key = str(getattr(settings, "object_storage_secret_key", "") or "")
    bucket = str(getattr(settings, "object_storage_bucket", "") or "")

    return ObjectStorageConfiguration(
        enabled=bool(endpoint and bucket),
        endpoint_host=parsed.hostname if parsed else None,
        endpoint_port=parsed.port if parsed else None,
        secure=bool(getattr(settings, "object_storage_secure", False)),
        region=str(getattr(settings, "object_storage_region", "") or ""),
        bucket_configured=bool(bucket),
        credentials_configured=bool(access_key and secret_key),
    )


def resolve_effective_configuration(
    settings: Any,
    *,
    database_revision: str,
    configuration_revision: str,
) -> EffectivePlatformConfiguration:
    return EffectivePlatformConfiguration(
        app_name=str(getattr(settings, "app_name", "")),
        app_version=str(getattr(settings, "app_version", "")),
        portal_port=int(getattr(settings, "portal_port", 3000)),
        cors_origins=list(getattr(settings, "cors_origins", [])),
        database=_database_configuration(str(getattr(settings, "database_url", "") or "")),
        object_storage=_object_storage_configuration(settings),
        ingestion=IngestionConfiguration(
            workspace_root=str(getattr(settings, "ingestion_workspace_root", "")),
            max_source_bytes=int(getattr(settings, "ingestion_max_source_bytes", 0)),
            worker_enabled=bool(getattr(settings, "feature_worker_enabled", False)),
        ),
        operational_health=OperationalHealthConfiguration(
            pending_warning_seconds=int(getattr(settings, "operational_health_pending_warning_seconds", 0)),
            stale_data_seconds=int(getattr(settings, "operational_health_stale_data_seconds", 0)),
            failed_run_critical_count=int(getattr(settings, "operational_health_failed_run_critical_count", 0)),
        ),
        feature_flags={
            "ai_provider_execution": False,
            "embeddings": bool(getattr(settings, "feature_embeddings_enabled", False)),
            "vector_retrieval": bool(getattr(settings, "feature_vector_retrieval_enabled", False)),
            "worker": bool(getattr(settings, "feature_worker_enabled", False)),
            "enterprise_extensions": bool(getattr(settings, "feature_enterprise_extensions_enabled", False)),
        },
        build_commit=str(getattr(settings, "build_commit", "unknown") or "unknown"),
        database_revision=database_revision,
        configuration_revision=configuration_revision,
        provider_execution_enabled=False,
    )
