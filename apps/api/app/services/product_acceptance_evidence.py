from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.product_acceptance import AcceptanceExecution, AcceptanceGate, AcceptanceResource
from app.schemas.product_acceptance import (
    AcceptanceExecutionCreate,
    AcceptanceExecutionUpdate,
    AcceptanceGateUpsert,
    AcceptanceResourceUpsert,
)


def _execution_to_dict(execution: AcceptanceExecution) -> dict[str, Any]:
    gates = sorted(
        execution.__dict__.get("_acceptance_gates", []) or [],
        key=lambda item: (item.phase_code, item.gate_code),
    )
    resources = sorted(
        execution.__dict__.get("_acceptance_resources", []) or [],
        key=lambda item: (item.resource_type, item.external_ref),
    )
    return {
        "id": execution.id,
        "execution_key": execution.execution_key,
        "correlation_id": execution.correlation_id,
        "scenario": execution.scenario,
        "status": execution.status,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "organization_id": execution.organization_id,
        "preserve_requested": execution.preserve_requested,
        "reuse_requested": execution.reuse_requested,
        "cleanup_requested": execution.cleanup_requested,
        "report": execution.report,
        "warnings": execution.warnings,
        "blockers": execution.blockers,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
        "gates": [_gate_to_dict(gate) for gate in gates],
        "resources": [_resource_to_dict(resource) for resource in resources],
    }


def _gate_to_dict(gate: AcceptanceGate) -> dict[str, Any]:
    return {
        "id": gate.id,
        "execution_id": gate.execution_id,
        "phase_code": gate.phase_code,
        "gate_code": gate.gate_code,
        "status": gate.status,
        "started_at": gate.started_at,
        "completed_at": gate.completed_at,
        "details": gate.details,
        "error_code": gate.error_code,
        "error_message": gate.error_message,
        "created_at": gate.created_at,
        "updated_at": gate.updated_at,
    }


def _resource_to_dict(resource: AcceptanceResource) -> dict[str, Any]:
    return {
        "id": resource.id,
        "execution_id": resource.execution_id,
        "resource_type": resource.resource_type,
        "resource_id": resource.resource_id,
        "external_ref": resource.external_ref,
        "created_by_execution": resource.created_by_execution,
        "reused": resource.reused,
        "cleanup_status": resource.cleanup_status,
        "details": resource.details,
        "created_at": resource.created_at,
        "updated_at": resource.updated_at,
    }


def _hydrate_execution(db: Session, execution: AcceptanceExecution) -> AcceptanceExecution:
    execution.__dict__["_acceptance_gates"] = (
        db.query(AcceptanceGate).filter(AcceptanceGate.execution_id == execution.id).all()
    )
    execution.__dict__["_acceptance_resources"] = (
        db.query(AcceptanceResource).filter(AcceptanceResource.execution_id == execution.id).all()
    )
    return execution


def create_or_get_acceptance_execution(
    db: Session,
    payload: AcceptanceExecutionCreate,
) -> dict[str, Any]:
    existing = (
        db.query(AcceptanceExecution).filter(AcceptanceExecution.execution_key == payload.execution_key).one_or_none()
    )
    if existing is not None:
        immutable_request = (
            existing.correlation_id,
            existing.scenario,
            existing.organization_id,
            existing.preserve_requested,
            existing.reuse_requested,
            existing.cleanup_requested,
        )
        replay_request = (
            payload.correlation_id,
            payload.scenario,
            payload.organization_id,
            payload.preserve_requested,
            payload.reuse_requested,
            payload.cleanup_requested,
        )
        if immutable_request != replay_request:
            raise ValueError("idempotency_key_conflict")
        return _execution_to_dict(_hydrate_execution(db, existing))

    execution = AcceptanceExecution(**payload.model_dump())
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return _execution_to_dict(_hydrate_execution(db, execution))


def list_acceptance_executions(
    db: Session,
    scenario: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = db.query(AcceptanceExecution)
    if scenario:
        query = query.filter(AcceptanceExecution.scenario == scenario)
    if status:
        query = query.filter(AcceptanceExecution.status == status)
    executions = query.order_by(AcceptanceExecution.created_at.desc()).limit(limit).all()
    return [_execution_to_dict(_hydrate_execution(db, execution)) for execution in executions]


def get_acceptance_execution(db: Session, execution_key: str) -> dict[str, Any] | None:
    execution = db.query(AcceptanceExecution).filter(AcceptanceExecution.execution_key == execution_key).one_or_none()
    if execution is None:
        return None
    return _execution_to_dict(_hydrate_execution(db, execution))


def update_acceptance_execution(
    db: Session,
    execution_key: str,
    payload: AcceptanceExecutionUpdate,
) -> dict[str, Any] | None:
    execution = db.query(AcceptanceExecution).filter(AcceptanceExecution.execution_key == execution_key).one_or_none()
    if execution is None:
        return None
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(execution, key, value)
    db.commit()
    db.refresh(execution)
    return _execution_to_dict(_hydrate_execution(db, execution))


def upsert_acceptance_gate(
    db: Session,
    execution_key: str,
    payload: AcceptanceGateUpsert,
) -> dict[str, Any] | None:
    execution = db.query(AcceptanceExecution).filter(AcceptanceExecution.execution_key == execution_key).one_or_none()
    if execution is None:
        return None
    gate = (
        db.query(AcceptanceGate)
        .filter(
            AcceptanceGate.execution_id == execution.id,
            AcceptanceGate.phase_code == payload.phase_code,
            AcceptanceGate.gate_code == payload.gate_code,
        )
        .one_or_none()
    )
    values = payload.model_dump()
    if gate is None:
        gate = AcceptanceGate(execution_id=execution.id, **values)
        db.add(gate)
    else:
        for key, value in values.items():
            setattr(gate, key, value)
    db.commit()
    db.refresh(gate)
    return _gate_to_dict(gate)


def upsert_acceptance_resource(
    db: Session,
    execution_key: str,
    payload: AcceptanceResourceUpsert,
) -> dict[str, Any] | None:
    execution = db.query(AcceptanceExecution).filter(AcceptanceExecution.execution_key == execution_key).one_or_none()
    if execution is None:
        return None
    resource = (
        db.query(AcceptanceResource)
        .filter(
            AcceptanceResource.execution_id == execution.id,
            AcceptanceResource.resource_type == payload.resource_type,
            AcceptanceResource.external_ref == payload.external_ref,
        )
        .one_or_none()
    )
    values = payload.model_dump()
    if resource is None:
        resource = AcceptanceResource(execution_id=execution.id, **values)
        db.add(resource)
    else:
        for key, value in values.items():
            setattr(resource, key, value)
    db.commit()
    db.refresh(resource)
    return _resource_to_dict(resource)
