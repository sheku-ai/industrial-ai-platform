from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")

logger = logging.getLogger(__name__)


def compose_runtime_dependency(
    db: Session,
    *,
    runtime: str,
    organization_id: uuid.UUID | None,
    dependency: str,
    required: bool,
    builder: Callable[[], T],
    optional_default: T,
) -> tuple[T, dict[str, Any]]:
    started_at = time.perf_counter()
    try:
        value = builder()
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.exception(
            "runtime_dependency_failed runtime=%s organization_id=%s dependency=%s "
            "error_type=%s duration_ms=%s required=%s result=%s",
            runtime,
            organization_id,
            dependency,
            type(exc).__name__,
            duration_ms,
            required,
            "total_failure" if required else "partial",
        )
        if required:
            raise
        db.rollback()
        return optional_default, {
            "dependency": dependency,
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "duration_ms": duration_ms,
            "required": False,
            "result": "partial",
        }

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "runtime_dependency_completed runtime=%s organization_id=%s dependency=%s "
        "duration_ms=%s required=%s result=success",
        runtime,
        organization_id,
        dependency,
        duration_ms,
        required,
    )
    return value, {
        "dependency": dependency,
        "status": "ready",
        "duration_ms": duration_ms,
        "required": required,
        "result": "success",
    }
