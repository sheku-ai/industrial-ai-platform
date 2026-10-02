from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.runtime_worker import RuntimeWorker
from app.security.resource_scope import ResourceScope
from app.services.correlation_context import current_correlation_id


def record_worker_transition(
    session: Session,
    *,
    worker: RuntimeWorker,
    action: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    actor_type: str,
    actor_id: str | None,
    organization_id: UUID | None = None,
    resource_scope: ResourceScope | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    effective_organization_id = resource_scope.organization_id if resource_scope is not None else organization_id
    scope_metadata = _scope_metadata(resource_scope)
    event_metadata = {
        "action": action,
        "correlation_id": current_correlation_id(),
        "worker_key": worker.worker_key,
        "instance_id": worker.instance_id,
        **scope_metadata,
        **(metadata or {}),
    }
    session.add(
        AuditEvent(
            organization_id=effective_organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type="runtime.worker",
            resource_id=str(worker.id),
            summary=f"runtime worker transition: {action}",
            metadata_json=event_metadata,
        )
    )
    session.add(
        AuditHistory(
            organization_id=effective_organization_id,
            entity_type="runtime.worker",
            entity_id=str(worker.id),
            action=action,
            before_state={**before_state, **scope_metadata},
            after_state={**after_state, **scope_metadata},
            actor_type=actor_type,
            actor_id=actor_id,
        )
    )


def _scope_metadata(resource_scope: ResourceScope | None) -> dict[str, Any]:
    if resource_scope is None:
        return {}
    return {
        "resource_scope": resource_scope.scope_type.value,
        "resource_scope_id": resource_scope.scope_id,
        "resource_scope_organization_id": str(resource_scope.organization_id)
        if resource_scope.organization_id
        else None,
    }
