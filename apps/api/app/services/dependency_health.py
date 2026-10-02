from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.dependency_health import (
    DependencyHealthItem,
    DependencyHealthResponse,
    ReadinessResponse,
)


def _database_dependency(session: Session | None) -> DependencyHealthItem:
    if session is None:
        return DependencyHealthItem(
            name="postgresql",
            required=True,
            enabled=True,
            status="unavailable",
            lifecycle_state="unavailable",
            detail="database session is unavailable",
        )

    try:
        session.execute(text("SELECT 1"))
    except Exception:
        session.rollback()
        return DependencyHealthItem(
            name="postgresql",
            required=True,
            enabled=True,
            status="unavailable",
            lifecycle_state="unavailable",
            detail="database connectivity check failed",
        )

    return DependencyHealthItem(
        name="postgresql",
        required=True,
        enabled=True,
        status="healthy",
        lifecycle_state="ready",
    )


def _identity_database_dependency(
    session: Session | None,
    *,
    required: bool,
) -> DependencyHealthItem:
    if session is None:
        return DependencyHealthItem(
            name="identity_postgresql",
            required=required,
            enabled=required,
            status="unavailable" if required else "not_configured",
            lifecycle_state="unavailable" if required else "degraded",
            detail="identity database session is unavailable",
        )
    try:
        session.execute(text("SELECT 1"))
        schema_ready = bool(
            session.scalar(
                text(
                    """
                    SELECT count(*) = 6
                    FROM information_schema.tables
                    WHERE table_schema = 'identity'
                      AND table_name = ANY(:tables)
                    """
                ),
                {
                    "tables": [
                        "users",
                        "password_credentials",
                        "organization_memberships",
                        "auth_sessions",
                        "authentication_events",
                        "login_throttles",
                    ]
                },
            )
        )
    except Exception:
        session.rollback()
        return DependencyHealthItem(
            name="identity_postgresql",
            required=True,
            enabled=True,
            status="unavailable",
            lifecycle_state="unavailable",
            detail="identity database connectivity check failed",
        )
    if not schema_ready:
        return DependencyHealthItem(
            name="identity_postgresql",
            required=True,
            enabled=True,
            status="unavailable",
            lifecycle_state="unavailable",
            detail="identity database schema is not ready",
        )
    return DependencyHealthItem(
        name="identity_postgresql",
        required=True,
        enabled=True,
        status="healthy",
        lifecycle_state="ready",
    )


def _optional_dependency(
    *,
    name: str,
    enabled: bool,
    configured: bool,
    detail: str,
    probe: Callable[[], bool] | None = None,
) -> DependencyHealthItem:
    if not enabled:
        return DependencyHealthItem(
            name=name,
            required=False,
            enabled=False,
            status="disabled",
            lifecycle_state="alive",
        )
    if not configured:
        return DependencyHealthItem(
            name=name,
            required=False,
            enabled=True,
            status="not_configured",
            lifecycle_state="degraded",
            detail=detail,
        )
    if probe is not None:
        try:
            available = bool(probe())
        except Exception:
            available = False
        if not available:
            return DependencyHealthItem(
                name=name,
                required=False,
                enabled=True,
                status="unavailable",
                lifecycle_state="degraded",
                detail=f"{name} connectivity check failed",
            )
    return DependencyHealthItem(
        name=name,
        required=False,
        enabled=True,
        status="healthy" if probe is not None else "configured",
        lifecycle_state="ready" if probe is not None else "alive",
        detail=(None if probe is not None else "connectivity is not required for core platform readiness"),
    )


def evaluate_dependency_health(
    session: Session | None,
    settings: Any,
    *,
    identity_session: Session | None = None,
    redis_probe: Callable[[], bool] | None = None,
    object_storage_probe: Callable[[], bool] | None = None,
) -> DependencyHealthResponse:
    now = datetime.now(UTC)
    database = _database_dependency(session)
    identity_required = True
    identity_database = _identity_database_dependency(
        identity_session,
        required=identity_required,
    )

    object_storage_endpoint = str(getattr(settings, "object_storage_endpoint_url", "") or "").strip()
    object_storage_bucket = str(getattr(settings, "object_storage_bucket", "") or "").strip()
    object_storage_enabled = bool(object_storage_endpoint or object_storage_bucket)
    probe_timeout = max(
        0.1,
        float(getattr(settings, "dependency_probe_timeout_seconds", 2.0)),
    )
    secret_store_provider = str(getattr(settings, "secret_store_provider", "memory") or "memory").strip().lower()
    redis_url = str(getattr(settings, "secret_store_redis_url", "") or "").strip()
    redis_enabled = secret_store_provider == "redis"

    if redis_probe is None and redis_enabled and redis_url:

        def redis_probe():
            return bool(
                Redis.from_url(
                    redis_url,
                    socket_connect_timeout=probe_timeout,
                    socket_timeout=probe_timeout,
                ).ping()
            )

    if object_storage_probe is None and object_storage_enabled and object_storage_endpoint and object_storage_bucket:

        def object_storage_probe():
            return _probe_object_storage(
                settings,
                timeout_seconds=probe_timeout,
            )

    embeddings_enabled = bool(getattr(settings, "feature_embeddings_enabled", False))
    vector_enabled = bool(getattr(settings, "feature_vector_retrieval_enabled", False))

    dependencies = [
        database,
        identity_database,
        _optional_dependency(
            name="object_storage",
            enabled=object_storage_enabled,
            configured=bool(object_storage_endpoint and object_storage_bucket),
            detail="object storage requires endpoint and bucket configuration",
            probe=object_storage_probe,
        ),
        _optional_dependency(
            name="redis_secret_store",
            enabled=redis_enabled,
            configured=bool(redis_url),
            detail="redis secret store requires SECRET_STORE_REDIS_URL",
            probe=redis_probe,
        ),
        _optional_dependency(
            name="embeddings",
            enabled=embeddings_enabled,
            configured=True,
            detail="embeddings are enabled but not configured",
        ),
        _optional_dependency(
            name="vector_retrieval",
            enabled=vector_enabled,
            configured=True,
            detail="vector retrieval is enabled but not configured",
        ),
        DependencyHealthItem(
            name="ai_provider_execution",
            required=False,
            enabled=False,
            status="disabled",
            lifecycle_state="alive",
            detail="provider execution remains disabled by policy",
        ),
    ]

    if database.status != "healthy" or (identity_required and identity_database.status != "healthy"):
        status = "critical"
    elif any(item.lifecycle_state == "degraded" for item in dependencies):
        status = "degraded"
    else:
        status = "healthy"
    return DependencyHealthResponse(status=status, checked_at=now, dependencies=dependencies)


def build_readiness(dependencies: DependencyHealthResponse) -> ReadinessResponse:
    required = [item for item in dependencies.dependencies if item.required]
    ready = all(item.lifecycle_state == "ready" for item in required)
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        lifecycle_state="ready" if ready else "unavailable",
        checked_at=dependencies.checked_at,
        required_dependencies=required,
    )


def _probe_object_storage(settings: Any, *, timeout_seconds: float) -> bool:
    client = boto3.client(
        "s3",
        endpoint_url=getattr(settings, "object_storage_endpoint_url", None) or None,
        region_name=getattr(settings, "object_storage_region", "us-east-1"),
        aws_access_key_id=getattr(settings, "object_storage_access_key", None) or None,
        aws_secret_access_key=getattr(settings, "object_storage_secret_key", None) or None,
        use_ssl=bool(getattr(settings, "object_storage_secure", False)),
        config=Config(
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries={"max_attempts": 0},
        ),
    )
    client.head_bucket(Bucket=str(settings.object_storage_bucket))
    return True
