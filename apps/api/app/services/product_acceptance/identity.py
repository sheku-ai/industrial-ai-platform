from __future__ import annotations

import re
import uuid

from app.services.product_acceptance.contracts import AcceptanceIdentity

_EXECUTION_RE = re.compile(r"^local-product-acceptance-(?P<value>[0-9a-fA-F-]{36})$")


def build_identity(execution_key: str | None = None) -> AcceptanceIdentity:
    value = _extract_uuid(execution_key) if execution_key else uuid.uuid4()
    short_id = value.hex[:8]
    key = execution_key or f"local-product-acceptance-{value}"
    return AcceptanceIdentity(
        execution_id=str(value),
        execution_key=key,
        correlation_id=f"correlation-{value}",
        organization_external_ref=f"acceptance-org-{value}",
        document_external_ref=f"acceptance-document-{value}",
        collection_external_ref=f"acceptance-collection-{value}",
        assistant_external_ref=f"acceptance-assistant-{value}",
        short_id=short_id,
    )


def idempotency_key(execution_key: str, phase: str, operation: str, external_ref: str) -> str:
    return f"{execution_key}:{phase}:{operation}:{external_ref}"


def _extract_uuid(execution_key: str | None) -> uuid.UUID:
    if not execution_key:
        return uuid.uuid4()
    match = _EXECUTION_RE.match(execution_key)
    if not match:
        raise ValueError("execution_key must match local-product-acceptance-<UUID>")
    return uuid.UUID(match.group("value"))
