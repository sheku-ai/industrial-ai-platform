from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.runtime_configuration import RuntimeConfiguration, RuntimeConfigurationRevision

ENTERPRISE_SEARCH_CONFIGURATION_TYPE = "enterprise_search"
ENTERPRISE_SEARCH_CONFIGURATION_KEY = "defaults"

PRODUCT_DEFAULT_LIMIT = 10
PRODUCT_MAX_LIMIT = 50
PRODUCT_DEFAULT_TOP_K = 10
PRODUCT_MAX_TOP_K = 100


@dataclass(frozen=True)
class EnterpriseSearchConfiguration:
    default_limit: int
    max_limit: int
    default_top_k: int
    max_top_k: int
    effective_limit: int
    effective_top_k: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "configuration_type": ENTERPRISE_SEARCH_CONFIGURATION_TYPE,
            "configuration_key": ENTERPRISE_SEARCH_CONFIGURATION_KEY,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
            "default_top_k": self.default_top_k,
            "max_top_k": self.max_top_k,
            "effective_limit": self.effective_limit,
            "effective_top_k": self.effective_top_k,
            "source": self.source,
        }


def _positive_int(value: Any, fallback: int, *, ceiling: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < 1:
        return fallback
    return min(parsed, ceiling)


def _normalize_payload(payload: dict[str, Any] | None) -> dict[str, int]:
    payload = payload or {}
    max_limit = _positive_int(payload.get("max_limit"), PRODUCT_MAX_LIMIT, ceiling=PRODUCT_MAX_LIMIT)
    max_top_k = _positive_int(payload.get("max_top_k"), PRODUCT_MAX_TOP_K, ceiling=PRODUCT_MAX_TOP_K)
    default_limit = _positive_int(payload.get("default_limit"), PRODUCT_DEFAULT_LIMIT, ceiling=max_limit)
    default_top_k = _positive_int(payload.get("default_top_k"), PRODUCT_DEFAULT_TOP_K, ceiling=max_top_k)
    return {
        "default_limit": min(default_limit, max_limit),
        "max_limit": max_limit,
        "default_top_k": min(default_top_k, max_top_k),
        "max_top_k": max_top_k,
    }


def _load_active_payload(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    statement = (
        select(RuntimeConfigurationRevision.payload)
        .join(
            RuntimeConfiguration,
            RuntimeConfiguration.id == RuntimeConfigurationRevision.configuration_id,
        )
        .where(RuntimeConfiguration.configuration_type == ENTERPRISE_SEARCH_CONFIGURATION_TYPE)
        .where(RuntimeConfiguration.configuration_key == ENTERPRISE_SEARCH_CONFIGURATION_KEY)
        .where(RuntimeConfigurationRevision.status == "active")
        .where(RuntimeConfigurationRevision.effective_from <= func.now())
        .where(
            or_(
                RuntimeConfigurationRevision.effective_until.is_(None),
                RuntimeConfigurationRevision.effective_until > func.now(),
            )
        )
    )
    if organization_id is None:
        statement = statement.where(
            RuntimeConfiguration.scope_type == "platform",
            RuntimeConfiguration.organization_id.is_(None),
        )
    else:
        statement = statement.where(
            RuntimeConfiguration.scope_type == "organization",
            RuntimeConfiguration.organization_id == organization_id,
        )
    return db.execute(statement.limit(1)).scalar_one_or_none()


def resolve_enterprise_search_configuration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    requested_limit: int | None,
    requested_top_k: int | None,
) -> EnterpriseSearchConfiguration:
    platform_payload = _load_active_payload(db, organization_id=None)
    organization_payload = _load_active_payload(db, organization_id=organization_id)

    merged_payload: dict[str, Any] = {}
    source = "product_fallback"
    if platform_payload is not None:
        merged_payload.update(platform_payload)
        source = "platform"
    if organization_payload is not None:
        merged_payload.update(organization_payload)
        source = "organization"

    normalized = _normalize_payload(merged_payload)

    if requested_limit is not None and requested_limit > normalized["max_limit"]:
        raise ValueError(f"limit exceeds configured maximum of {normalized['max_limit']}")
    if requested_top_k is not None and requested_top_k > normalized["max_top_k"]:
        raise ValueError(f"top_k exceeds configured maximum of {normalized['max_top_k']}")

    effective_limit = requested_limit if requested_limit is not None else normalized["default_limit"]
    effective_top_k = requested_top_k if requested_top_k is not None else normalized["default_top_k"]

    return EnterpriseSearchConfiguration(
        default_limit=normalized["default_limit"],
        max_limit=normalized["max_limit"],
        default_top_k=normalized["default_top_k"],
        max_top_k=normalized["max_top_k"],
        effective_limit=effective_limit,
        effective_top_k=effective_top_k,
        source=source,
    )
