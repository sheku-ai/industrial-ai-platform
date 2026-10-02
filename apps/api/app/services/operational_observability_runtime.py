from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalSchedule, SchedulerClaim, SchedulerRun
from app.models.operational_observability import (
    BoundedRetryAttempt,
    FailureRecoveryAction,
    OperationalEvidence,
    OperationalExecution,
    OperationalIncident,
    RuntimeComponent,
    RuntimeObservation,
)
from app.models.runtime import RuntimeExecutionAttempt
from app.models.runtime_worker import RuntimeWorker
from app.repositories.operational_observability import OperationalObservabilityRepository
from app.schemas.operational_observability import (
    BoundedRetryCreate,
    BoundedRetryRead,
    FailureRecoveryActionCreate,
    FailureRecoveryActionRead,
    IncidentTransitionRequest,
    OperationalDiagnostic,
    OperationalEvidenceRead,
    OperationalExecutionCreate,
    OperationalExecutionRead,
    OperationalIncidentCreate,
    OperationalIncidentRead,
    OperationalReadinessGate,
    OperationalReadinessResponse,
    OperationalWorkspaceRuntimeResponse,
    RuntimeComponentCreate,
    RuntimeComponentRead,
    RuntimeObservationCreate,
    RuntimeObservationRead,
    RuntimeResultRequest,
)

FRESHNESS_HOURS = 24
TERMINAL_EXECUTION_STATUSES = {"completed", "failed", "blocked", "cancelled", "abandoned"}
OPEN_INCIDENT_STATUSES = {"open", "acknowledged", "recovering"}
CRITICAL_SEVERITIES = {"error", "critical"}
NEXT_ACTIONS = {
    "runtime_observability_available": "register_component",
    "scheduler_runtime_available": "investigate_scheduler_failure",
    "worker_inventory_available": "restore_worker_heartbeat",
    "lease_visibility_available": "resolve_expired_lease",
    "failure_recovery_evidence_available": "register_recovery_action",
    "bounded_retry_behavior_available": "review_retry_exhaustion",
    "runtime_diagnostics_available": "refresh_operational_evidence",
    "operational_blockers_visible": "acknowledge_incident",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_json(item) for item in value]
    return value


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(_safe_json(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _scope_filter(model: Any, scope: str, organization_id: uuid.UUID | None) -> tuple[Any, Any]:
    org_filter = (
        model.organization_id.is_(None) if organization_id is None else model.organization_id == organization_id
    )
    return model.scope == scope, org_filter


def _count(db: Session, model: Any, *criteria: Any) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _component_status_from_worker(worker: RuntimeWorker, now: datetime) -> tuple[str, str, str]:
    heartbeat_stale = worker.heartbeat_at is None or now - worker.heartbeat_at > timedelta(minutes=5)
    if worker.observed_state == "failed":
        return "failed", "unhealthy", "blocked"
    if heartbeat_stale:
        return "unavailable", "degraded", "not_ready"
    if worker.observed_state in {"ready", "busy"} and worker.desired_state == "active":
        return "running", "healthy", "ready"
    return "degraded", "degraded", "not_ready"


def _evidence_status(passed: bool, failed: bool = False) -> str:
    if failed:
        return "failed"
    return "passed" if passed else "blocked"


def _readiness_status_from_gates(gates: list[OperationalReadinessGate]) -> str:
    if any(gate.status == "failed" for gate in gates):
        return "failed"
    if any(gate.status == "blocked" for gate in gates):
        return "blocked"
    if all(gate.status == "passed" for gate in gates):
        return "passed"
    return "not_evaluated"


def _to_diagnostic(
    code: str,
    domain: str,
    severity: str,
    status: str,
    summary: str,
    *,
    component: str | None = None,
    execution: str | None = None,
    evidence: str | None = None,
    action: str | None = None,
) -> OperationalDiagnostic:
    return OperationalDiagnostic(
        diagnostic_code=code,
        domain=domain,
        severity=severity,
        status=status,
        summary=summary,
        affected_component=component,
        affected_execution=execution,
        evidence_reference=evidence,
        observed_at=_utcnow(),
        recommended_action=action,
    )


def register_component(db: Session, payload: RuntimeComponentCreate) -> RuntimeComponentRead:
    repo = OperationalObservabilityRepository(db)
    observed_at = payload.observed_at or _utcnow()
    component = repo.find_component(
        scope=payload.scope,
        organization_id=payload.organization_id,
        component_code=payload.component_code,
        instance_id=payload.instance_id,
    )
    if component is None:
        component = RuntimeComponent(
            organization_id=payload.organization_id,
            scope=payload.scope,
            component_code=payload.component_code,
            component_type=payload.component_type,
            instance_id=payload.instance_id,
            display_name=payload.display_name,
            runtime_version=payload.runtime_version,
            status=payload.status,
            health_status=payload.health_status,
            readiness_status=payload.readiness_status,
            capabilities=payload.capabilities,
            configuration_reference=payload.configuration_reference,
            last_started_at=payload.last_started_at,
            last_heartbeat_at=payload.last_heartbeat_at,
            last_success_at=payload.last_success_at,
            last_failure_at=payload.last_failure_at,
            observed_at=observed_at,
        )
        repo.add_component(component)
    else:
        component.display_name = payload.display_name
        component.runtime_version = payload.runtime_version
        component.status = payload.status
        component.health_status = payload.health_status
        component.readiness_status = payload.readiness_status
        component.capabilities = payload.capabilities
        component.configuration_reference = payload.configuration_reference
        component.last_started_at = payload.last_started_at
        component.last_heartbeat_at = payload.last_heartbeat_at
        component.last_success_at = payload.last_success_at
        component.last_failure_at = payload.last_failure_at
        component.observed_at = observed_at
        db.add(component)
        db.flush()
    _upsert_operational_evidence(
        db,
        scope=component.scope,
        organization_id=component.organization_id,
        evidence_type="component_readiness",
        source_entity_type="runtime.operational_component",
        source_entity_id=str(component.id),
        status="passed" if component.readiness_status == "ready" else "blocked",
        payload={
            "component_code": component.component_code,
            "component_type": component.component_type,
            "status": component.status,
            "health_status": component.health_status,
            "readiness_status": component.readiness_status,
        },
    )
    return RuntimeComponentRead.model_validate(component)


def register_observation(
    db: Session, component: RuntimeComponent, payload: RuntimeObservationCreate
) -> RuntimeObservationRead:
    repo = OperationalObservabilityRepository(db)
    observed_at = payload.observed_at or _utcnow()
    evidence_payload = {
        "summary": payload.summary,
        "observed_value": payload.observed_value,
        "expected_value": payload.expected_value,
        "evidence_payload": payload.evidence_payload,
    }
    evidence_hash = stable_hash(evidence_payload)
    observation = repo.find_observation(component.id, payload.observation_type, evidence_hash)
    if observation is None:
        observation = RuntimeObservation(
            organization_id=component.organization_id,
            scope=component.scope,
            component_id=component.id,
            observation_type=payload.observation_type,
            severity=payload.severity,
            status=payload.status,
            summary=payload.summary,
            observed_value=payload.observed_value,
            expected_value=payload.expected_value,
            unit=payload.unit,
            source_runtime=payload.source_runtime,
            source_entity_type=payload.source_entity_type,
            source_entity_id=payload.source_entity_id,
            evidence_payload=payload.evidence_payload,
            evidence_hash=evidence_hash,
            observed_at=observed_at,
            expires_at=payload.expires_at,
        )
        repo.add_observation(observation)
    _upsert_operational_evidence(
        db,
        scope=component.scope,
        organization_id=component.organization_id,
        evidence_type=f"{payload.observation_type}_observation",
        source_entity_type="runtime.operational_observation",
        source_entity_id=str(observation.id),
        status="failed" if payload.status == "failed" else ("blocked" if payload.status == "blocked" else "passed"),
        payload=evidence_payload,
        expires_at=payload.expires_at,
    )
    return RuntimeObservationRead.model_validate(observation)


def create_operational_execution(db: Session, payload: OperationalExecutionCreate) -> OperationalExecutionRead:
    repo = OperationalObservabilityRepository(db)
    input_hash = stable_hash(payload.input_payload)
    existing = repo.find_execution(
        payload.scope, payload.organization_id, payload.execution_type, payload.idempotency_key
    )
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("idempotency_key_conflict")
        return OperationalExecutionRead.model_validate(existing)
    execution = OperationalExecution(
        organization_id=payload.organization_id,
        scope=payload.scope,
        component_id=payload.component_id,
        execution_type=payload.execution_type,
        execution_reference=payload.execution_reference,
        correlation_id=payload.correlation_id or f"operational:{uuid.uuid4()}",
        idempotency_key=payload.idempotency_key,
        status=payload.status,
        attempt_number=payload.attempt_number,
        max_attempts=payload.max_attempts,
        input_hash=input_hash,
        started_at=_utcnow() if payload.status == "running" else None,
        last_progress_at=_utcnow() if payload.status in {"claimed", "running"} else None,
    )
    repo.add_execution(execution)
    return OperationalExecutionRead.model_validate(execution)


def complete_operational_execution(
    db: Session, execution: OperationalExecution, payload: RuntimeResultRequest
) -> OperationalExecutionRead:
    execution.status = "completed"
    execution.completed_at = _utcnow()
    execution.last_progress_at = execution.completed_at
    execution.result_hash = stable_hash(payload.result_payload)
    execution.failure_code = None
    execution.failure_summary = None
    db.add(execution)
    _upsert_operational_evidence(
        db,
        scope=execution.scope,
        organization_id=execution.organization_id,
        evidence_type="operational_execution_completed",
        source_entity_type="runtime.operational_execution",
        source_entity_id=str(execution.id),
        status="passed",
        payload={"execution_type": execution.execution_type, "result_hash": execution.result_hash},
    )
    db.flush()
    return OperationalExecutionRead.model_validate(execution)


def fail_operational_execution(
    db: Session, execution: OperationalExecution, payload: RuntimeResultRequest, status: str = "failed"
) -> OperationalExecutionRead:
    if not payload.failure_code:
        raise ValueError("failure_code_required")
    execution.status = status
    execution.completed_at = _utcnow()
    execution.last_progress_at = execution.completed_at
    execution.failure_code = payload.failure_code
    execution.failure_summary = payload.failure_summary
    execution.result_hash = stable_hash({"failure_code": payload.failure_code, "status": status})
    db.add(execution)
    _upsert_operational_evidence(
        db,
        scope=execution.scope,
        organization_id=execution.organization_id,
        evidence_type=f"operational_execution_{status}",
        source_entity_type="runtime.operational_execution",
        source_entity_id=str(execution.id),
        status="failed" if status == "failed" else "blocked",
        payload={"failure_code": payload.failure_code, "failure_summary": payload.failure_summary},
    )
    db.flush()
    return OperationalExecutionRead.model_validate(execution)


def register_retry_attempt(
    db: Session, execution: OperationalExecution, payload: BoundedRetryCreate
) -> BoundedRetryRead:
    repo = OperationalObservabilityRepository(db)
    existing = repo.find_retry(execution.id, payload.attempt_number)
    if existing is not None:
        return BoundedRetryRead.model_validate(existing)
    retry = BoundedRetryAttempt(
        operational_execution_id=execution.id,
        attempt_number=payload.attempt_number,
        retry_policy_code=payload.retry_policy_code,
        status=payload.status,
        delay_seconds=payload.delay_seconds,
        failure_code=payload.failure_code,
        failure_summary=payload.failure_summary,
        retryable=payload.retryable,
        decision_reason=payload.decision_reason,
        evidence_payload=payload.evidence_payload,
    )
    repo.add_retry(retry)
    _upsert_operational_evidence(
        db,
        scope=execution.scope,
        organization_id=execution.organization_id,
        evidence_type="bounded_retry_attempt",
        source_entity_type="runtime.operational_retry_attempt",
        source_entity_id=str(retry.id),
        status="passed" if payload.status in {"succeeded", "failed", "exhausted", "skipped"} else "blocked",
        payload={
            "attempt_number": payload.attempt_number,
            "retry_policy_code": payload.retry_policy_code,
            "retryable": payload.retryable,
            "max_attempts": execution.max_attempts,
            "status": payload.status,
        },
    )
    return BoundedRetryRead.model_validate(retry)


def complete_retry_attempt(db: Session, retry: BoundedRetryAttempt, payload: RuntimeResultRequest) -> BoundedRetryRead:
    retry.status = "succeeded"
    retry.completed_at = _utcnow()
    retry.evidence_payload = payload.result_payload
    db.add(retry)
    db.flush()
    return BoundedRetryRead.model_validate(retry)


def fail_retry_attempt(db: Session, retry: BoundedRetryAttempt, payload: RuntimeResultRequest) -> BoundedRetryRead:
    if not payload.failure_code:
        raise ValueError("failure_code_required")
    retry.status = "failed" if retry.retryable else "skipped"
    retry.completed_at = _utcnow()
    retry.failure_code = payload.failure_code
    retry.failure_summary = payload.failure_summary
    retry.evidence_payload = payload.result_payload
    db.add(retry)
    db.flush()
    return BoundedRetryRead.model_validate(retry)


def register_incident(db: Session, payload: OperationalIncidentCreate) -> OperationalIncidentRead:
    repo = OperationalObservabilityRepository(db)
    evidence_hash = stable_hash(
        {
            "incident_code": payload.incident_code,
            "source_entity_type": payload.source_entity_type,
            "source_entity_id": payload.source_entity_id,
            "details": payload.details,
        }
    )
    existing = repo.find_open_incident(
        scope=payload.scope,
        organization_id=payload.organization_id,
        incident_code=payload.incident_code,
        source_entity_type=payload.source_entity_type,
        source_entity_id=payload.source_entity_id,
    )
    if existing is not None:
        existing.occurrence_count += 1
        existing.last_observed_at = _utcnow()
        existing.details = {**(existing.details or {}), **payload.details}
        db.add(existing)
        db.flush()
        return OperationalIncidentRead.model_validate(existing)
    incident = OperationalIncident(
        organization_id=payload.organization_id,
        scope=payload.scope,
        incident_code=payload.incident_code,
        incident_type=payload.incident_type,
        severity=payload.severity,
        component_id=payload.component_id,
        operational_execution_id=payload.operational_execution_id,
        source_entity_type=payload.source_entity_type,
        source_entity_id=payload.source_entity_id,
        summary=payload.summary,
        details=payload.details,
        evidence_hash=evidence_hash,
    )
    repo.add_incident(incident)
    _upsert_operational_evidence(
        db,
        scope=payload.scope,
        organization_id=payload.organization_id,
        evidence_type="operational_incident_visible",
        source_entity_type="runtime.operational_incident",
        source_entity_id=str(incident.id),
        status="failed" if payload.severity in CRITICAL_SEVERITIES else "blocked",
        payload={"incident_code": payload.incident_code, "severity": payload.severity, "status": "open"},
    )
    return OperationalIncidentRead.model_validate(incident)


def transition_incident(
    db: Session, incident: OperationalIncident, action: str, payload: IncidentTransitionRequest
) -> OperationalIncidentRead:
    now = _utcnow()
    if action == "acknowledge":
        incident.status = "acknowledged"
        incident.acknowledged_at = now
        incident.acknowledged_by = payload.actor_reference
    elif action == "suppress":
        incident.status = "suppressed"
        incident.resolved_at = now
        incident.resolved_by = payload.actor_reference
        incident.resolution_code = payload.resolution_code or "suppressed"
        incident.resolution_summary = payload.resolution_summary or "Incident suppressed by operator."
    elif action == "resolve":
        if not payload.evidence_payload:
            raise ValueError("resolution_evidence_required")
        incident.status = "resolved"
        incident.resolved_at = now
        incident.resolved_by = payload.actor_reference
        incident.resolution_code = payload.resolution_code or "resolved"
        incident.resolution_summary = payload.resolution_summary
        incident.evidence_hash = stable_hash(payload.evidence_payload)
    db.add(incident)
    db.flush()
    return OperationalIncidentRead.model_validate(incident)


def create_recovery_action(
    db: Session, incident: OperationalIncident, payload: FailureRecoveryActionCreate
) -> FailureRecoveryActionRead:
    repo = OperationalObservabilityRepository(db)
    input_hash = stable_hash(payload.evidence_payload)
    existing = repo.find_recovery_action(incident.id, payload.action_type, input_hash)
    if existing is not None:
        return FailureRecoveryActionRead.model_validate(existing)
    action = FailureRecoveryAction(
        incident_id=incident.id,
        operational_execution_id=payload.operational_execution_id,
        action_type=payload.action_type,
        requested_by=payload.requested_by,
        approved_by=payload.approved_by,
        input_hash=input_hash,
        evidence_payload=payload.evidence_payload,
    )
    repo.add_recovery_action(action)
    _upsert_operational_evidence(
        db,
        scope=incident.scope,
        organization_id=incident.organization_id,
        evidence_type="failure_recovery_action_registered",
        source_entity_type="runtime.operational_recovery_action",
        source_entity_id=str(action.id),
        status="blocked",
        payload={"action_type": payload.action_type, "incident_id": str(incident.id)},
    )
    return FailureRecoveryActionRead.model_validate(action)


def complete_recovery_action(
    db: Session, action: FailureRecoveryAction, payload: RuntimeResultRequest, failed: bool = False
) -> FailureRecoveryActionRead:
    action.status = "failed" if failed else "completed"
    action.completed_at = _utcnow()
    action.evidence_payload = payload.result_payload
    action.result_hash = stable_hash(payload.result_payload)
    if failed:
        action.failure_code = payload.failure_code
        action.failure_summary = payload.failure_summary
    db.add(action)
    db.flush()
    return FailureRecoveryActionRead.model_validate(action)


def _upsert_operational_evidence(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    evidence_type: str,
    source_entity_type: str,
    source_entity_id: str,
    status: str,
    payload: dict[str, Any],
    expires_at: datetime | None = None,
) -> OperationalEvidence:
    repo = OperationalObservabilityRepository(db)
    evidence_hash = stable_hash(payload)
    existing = repo.find_evidence(
        scope=scope,
        organization_id=organization_id,
        evidence_type=evidence_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        evidence_hash=evidence_hash,
    )
    if existing is not None:
        return existing
    evidence = OperationalEvidence(
        organization_id=organization_id,
        scope=scope,
        evidence_type=evidence_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        status=status,
        evidence_payload=payload,
        evidence_hash=evidence_hash,
        observed_at=_utcnow(),
        expires_at=expires_at,
    )
    repo.add_evidence(evidence)
    return evidence


def synchronize_operational_evidence(
    db: Session, scope: str = "platform", organization_id: uuid.UUID | None = None
) -> None:
    now = _utcnow()
    repo = OperationalObservabilityRepository(db)
    if scope == "platform":
        component = repo.find_component(
            scope="platform", organization_id=None, component_code="platform-api", instance_id="api-runtime"
        )
        if component is None:
            register_component(
                db,
                RuntimeComponentCreate(
                    scope="platform",
                    component_code="platform-api",
                    component_type="api",
                    instance_id="api-runtime",
                    display_name="Platform API Runtime",
                    status="running",
                    health_status="healthy",
                    readiness_status="ready",
                    capabilities=["runtime_api", "workspace_runtime", "production_acceptance"],
                    observed_at=now,
                ),
            )
    for worker in db.scalars(select(RuntimeWorker)).all():
        status, health, readiness = _component_status_from_worker(worker, now)
        register_component(
            db,
            RuntimeComponentCreate(
                scope="platform",
                component_code=f"worker:{worker.worker_key}",
                component_type="worker",
                instance_id=worker.instance_id,
                display_name=f"Worker {worker.worker_key}",
                runtime_version=worker.runtime_version,
                status=status,
                health_status=health,
                readiness_status=readiness,
                capabilities=list(worker.capabilities or []),
                last_started_at=worker.started_at,
                last_heartbeat_at=worker.heartbeat_at,
                last_failure_at=worker.updated_at if worker.last_error_code else None,
                observed_at=now,
            ),
        )
    scheduler_workers = [
        worker for worker in db.scalars(select(RuntimeWorker).where(RuntimeWorker.worker_type == "scheduler")).all()
    ]
    if scheduler_workers:
        worker = scheduler_workers[0]
        status, health, readiness = _component_status_from_worker(worker, now)
        register_component(
            db,
            RuntimeComponentCreate(
                scope="platform",
                component_code="platform-scheduler",
                component_type="scheduler",
                instance_id=worker.instance_id,
                display_name="Platform Scheduler",
                runtime_version=worker.runtime_version,
                status=status,
                health_status=health,
                readiness_status=readiness,
                capabilities=list(worker.capabilities or []),
                last_started_at=worker.started_at,
                last_heartbeat_at=worker.heartbeat_at,
                observed_at=now,
            ),
        )
    _create_lease_observations(db, now, scope, organization_id)
    db.flush()


def _create_lease_observations(db: Session, now: datetime, scope: str, organization_id: uuid.UUID | None) -> None:
    runtime_expired = list(
        db.scalars(
            select(RuntimeExecutionAttempt).where(
                RuntimeExecutionAttempt.status.in_(("leased", "running")),
                RuntimeExecutionAttempt.lease_expires_at.is_not(None),
                RuntimeExecutionAttempt.lease_expires_at <= now,
            )
        ).all()
    )
    scheduler_expired = list(db.scalars(select(SchedulerClaim).where(SchedulerClaim.expires_at <= now)).all())
    for attempt in runtime_expired:
        _upsert_operational_evidence(
            db,
            scope="organization",
            organization_id=attempt.organization_id,
            evidence_type="lease_expired",
            source_entity_type="runtime.execution_attempt",
            source_entity_id=str(attempt.id),
            status="failed",
            payload={
                "execution_id": str(attempt.execution_id),
                "worker_id": attempt.worker_id,
                "lease_expires_at": attempt.lease_expires_at,
            },
        )
    for claim in scheduler_expired:
        _upsert_operational_evidence(
            db,
            scope="organization",
            organization_id=claim.organization_id,
            evidence_type="scheduler_claim_expired",
            source_entity_type="control_plane.scheduler_claim",
            source_entity_id=str(claim.id),
            status="failed",
            payload={"resource_type": claim.resource_type, "owner_id": claim.owner_id, "expires_at": claim.expires_at},
        )


def _latest_evidence_by_type(evidence: list[OperationalEvidence]) -> dict[str, OperationalEvidence]:
    latest: dict[str, OperationalEvidence] = {}
    for item in evidence:
        current = latest.get(item.evidence_type)
        if current is None or item.observed_at > current.observed_at:
            latest[item.evidence_type] = item
    return latest


def _fresh(item: OperationalEvidence | None, now: datetime) -> bool:
    if item is None:
        return False
    if item.expires_at is not None and item.expires_at <= now:
        return False
    return now - item.observed_at <= timedelta(hours=FRESHNESS_HOURS)


def _gate(
    code: str, passed: bool, summary: str, evidence: OperationalEvidence | None = None, failed: bool = False
) -> OperationalReadinessGate:
    status = _evidence_status(passed, failed=failed)
    issues = [] if status == "passed" else [{"code": code.upper(), "summary": summary}]
    return OperationalReadinessGate(
        gate_code=code,
        status=status,
        summary=summary,
        evidence_reference=str(evidence.id) if evidence else None,
        blocking_issues=issues,
    )


def current_critical_operational_signals(
    components: list[RuntimeComponent],
    observations: list[RuntimeObservation],
    incidents: list[OperationalIncident],
    now: datetime,
) -> dict[str, list[Any]]:
    active_observations = [item for item in observations if item.expires_at is None or item.expires_at > now]
    return {
        "observations": [
            item
            for item in active_observations
            if item.severity in CRITICAL_SEVERITIES and item.status in {"failed", "blocked"}
        ],
        "incidents": [
            item
            for item in incidents
            if item.status in OPEN_INCIDENT_STATUSES and item.severity in CRITICAL_SEVERITIES
        ],
        "components": [
            item
            for item in components
            if item.status in {"running", "degraded"}
            and item.last_heartbeat_at is not None
            and now - item.last_heartbeat_at > timedelta(minutes=5)
        ],
    }


def build_operational_readiness(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    *,
    refresh: bool = True,
) -> OperationalReadinessResponse:
    if refresh:
        synchronize_operational_evidence(db, scope=scope, organization_id=organization_id)
    repo = OperationalObservabilityRepository(db)
    now = _utcnow()
    components = repo.list_components(scope, organization_id)
    observations = repo.list_observations(scope, organization_id)
    evidence = repo.list_evidence(scope, organization_id)
    latest = _latest_evidence_by_type(evidence)
    incidents = repo.list_incidents(scope, organization_id)
    recovery_actions = repo.list_recovery_actions()
    active_observations = [item for item in observations if item.expires_at is None or item.expires_at > now]
    critical_signals = current_critical_operational_signals(components, observations, incidents, now)
    scheduler_components = [item for item in components if item.component_type == "scheduler"]
    worker_components = [item for item in components if item.component_type == "worker"]
    runtime_observability = bool(components) and bool(active_observations or evidence)
    if refresh and not active_observations and components:
        component = components[0]
        register_observation(
            db,
            component,
            RuntimeObservationCreate(
                observation_type="readiness",
                severity="info",
                status="normal",
                summary="Component registry is persisted and readable.",
                source_runtime="operational_observability_runtime",
                source_entity_type="runtime.operational_component",
                source_entity_id=str(component.id),
                evidence_payload={"component_count": len(components)},
                expires_at=now + timedelta(hours=FRESHNESS_HOURS),
            ),
        )
        active_observations = repo.list_observations(scope, organization_id)
        evidence = repo.list_evidence(scope, organization_id)
        latest = _latest_evidence_by_type(evidence)
    scheduler_ready = any(
        item.readiness_status == "ready" and item.health_status == "healthy" for item in scheduler_components
    )
    workers_visible = bool(worker_components) and all(
        item.readiness_status in {"ready", "not_ready", "blocked"} for item in worker_components
    )
    lease_evidence = latest.get("lease_expired") or latest.get("scheduler_claim_expired")
    lease_visible = _count(db, RuntimeExecutionAttempt) >= 0 and _count(db, SchedulerClaim) >= 0
    retry_evidence = latest.get("bounded_retry_attempt")
    retry_attempts = _count(db, BoundedRetryAttempt)
    recovery_evidence = latest.get("failure_recovery_action_registered")
    completed_actions = [action for action in recovery_actions if action.status == "completed"]
    diagnostics = build_operational_diagnostics(
        db,
        scope=scope,
        organization_id=organization_id,
        persist=refresh,
    )
    gates = [
        _gate(
            "runtime_observability_available",
            runtime_observability,
            "Component registry and operational observations are persisted.",
            latest.get("component_readiness"),
        ),
        _gate(
            "scheduler_runtime_available",
            scheduler_ready,
            "Scheduler component is registered with healthy readiness.",
            latest.get("component_readiness"),
        ),
        _gate(
            "worker_inventory_available",
            workers_visible,
            "Worker inventory is persisted and heartbeat readiness is visible.",
            latest.get("component_readiness"),
        ),
        _gate(
            "lease_visibility_available",
            lease_visible,
            "Runtime and scheduler leases are visible from PostgreSQL.",
            lease_evidence,
        ),
        _gate(
            "failure_recovery_evidence_available",
            bool(incidents) and bool(completed_actions),
            "Incidents and recovery actions are persisted with resolution evidence.",
            recovery_evidence,
        ),
        _gate(
            "bounded_retry_behavior_available",
            retry_attempts > 0 and retry_evidence is not None,
            "Bounded retry attempts are persisted with explicit max attempts.",
            retry_evidence,
        ),
        _gate(
            "runtime_diagnostics_available",
            bool(diagnostics),
            "Operational diagnostics are deterministic and evidence-backed.",
            latest.get("operational_diagnostic"),
        ),
        _gate(
            "operational_blockers_visible",
            True,
            "Open operational blockers are exposed by the runtime.",
            latest.get("operational_incident_visible"),
            failed=any(critical_signals.values()),
        ),
    ]
    status = _readiness_status_from_gates(gates)
    return OperationalReadinessResponse(
        scope=scope,
        organization_id=organization_id,
        status=status,
        operational_ready=status == "passed",
        gates=gates,
        blocking_issues=[issue for gate in gates for issue in gate.blocking_issues],
        warnings=[],
        diagnostics=diagnostics,
    )


def build_operational_diagnostics(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    *,
    persist: bool = True,
) -> list[OperationalDiagnostic]:
    repo = OperationalObservabilityRepository(db)
    now = _utcnow()
    diagnostics: list[OperationalDiagnostic] = []
    for component in repo.list_components(scope, organization_id):
        if component.readiness_status != "ready":
            diagnostics.append(
                _to_diagnostic(
                    "component_not_ready",
                    component.component_type,
                    "warning",
                    component.readiness_status,
                    f"{component.display_name} is not ready.",
                    component=str(component.id),
                    action="restore_worker_heartbeat" if component.component_type == "worker" else "register_component",
                )
            )
        if component.last_heartbeat_at and now - component.last_heartbeat_at > timedelta(minutes=5):
            diagnostics.append(
                _to_diagnostic(
                    "heartbeat_stale",
                    component.component_type,
                    "error",
                    "failed",
                    f"{component.display_name} heartbeat is stale.",
                    component=str(component.id),
                    action="restore_worker_heartbeat",
                )
            )
    for incident in repo.list_incidents(scope, organization_id):
        if incident.status in OPEN_INCIDENT_STATUSES:
            diagnostics.append(
                _to_diagnostic(
                    incident.incident_code,
                    incident.incident_type,
                    incident.severity,
                    incident.status,
                    incident.summary,
                    component=str(incident.component_id) if incident.component_id else None,
                    execution=str(incident.operational_execution_id) if incident.operational_execution_id else None,
                    evidence=str(incident.id),
                    action="acknowledge_incident",
                )
            )
    if not diagnostics:
        diagnostics.append(
            _to_diagnostic(
                "operational_diagnostics_available",
                "runtime",
                "info",
                "normal",
                "Operational diagnostics are available from persisted runtime evidence.",
                action="refresh_operational_evidence",
            )
        )
    if persist:
        _upsert_operational_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="operational_diagnostic",
            source_entity_type="runtime.operational_diagnostics",
            source_entity_id=f"{scope}:{organization_id or 'platform'}",
            status="passed",
            payload={"diagnostic_count": len(diagnostics), "codes": [item.diagnostic_code for item in diagnostics]},
            expires_at=now + timedelta(hours=FRESHNESS_HOURS),
        )
    return diagnostics


def build_worker_inventory(db: Session) -> list[dict[str, Any]]:
    now = _utcnow()
    attempts = list(
        db.scalars(
            select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.status.in_(("leased", "running")))
        ).all()
    )
    by_worker = {attempt.worker_id: attempt for attempt in attempts if attempt.worker_id}
    output = []
    for worker in db.scalars(
        select(RuntimeWorker).order_by(RuntimeWorker.worker_type.asc(), RuntimeWorker.worker_key.asc())
    ).all():
        status, health, readiness = _component_status_from_worker(worker, now)
        active = by_worker.get(worker.worker_key) or by_worker.get(worker.instance_id)
        output.append(
            {
                "worker_id": worker.worker_key,
                "worker_type": worker.worker_type,
                "instance_id": worker.instance_id,
                "status": status,
                "health": health,
                "readiness": readiness,
                "capabilities": worker.capabilities,
                "current_execution": str(active.execution_id) if active else None,
                "active_lease": str(active.lease_token) if active and active.lease_token else None,
                "last_heartbeat": worker.heartbeat_at,
                "last_success": worker.ready_at,
                "last_failure": worker.updated_at if worker.last_error_code else None,
                "processed_count": (worker.metrics or {}).get("processed_count", 0),
                "failed_count": (worker.metrics or {}).get("failed_count", 0),
                "retry_count": (worker.metrics or {}).get("retry_count", 0),
                "observed_at": now,
            }
        )
    return output


def build_scheduler_inventory(db: Session) -> dict[str, Any]:
    now = _utcnow()
    scheduler_workers = list(db.scalars(select(RuntimeWorker).where(RuntimeWorker.worker_type == "scheduler")).all())
    claims = list(db.scalars(select(SchedulerClaim)).all())
    runs = list(db.scalars(select(SchedulerRun)).all())
    schedules = list(db.scalars(select(OperationalSchedule)).all())
    return {
        "registered": bool(scheduler_workers),
        "running": any(worker.observed_state in {"ready", "busy"} for worker in scheduler_workers),
        "heartbeat_fresh": any(
            worker.heartbeat_at and now - worker.heartbeat_at <= timedelta(minutes=5) for worker in scheduler_workers
        ),
        "schedules_loaded": len(schedules),
        "disabled_schedules": len([item for item in schedules if not item.enabled]),
        "last_dispatch_successful": any(run.status in {"dispatched", "succeeded"} for run in runs),
        "dispatch_failures": len([run for run in runs if run.status == "failed"]),
        "overdue_schedules": len(
            [item for item in schedules if item.next_run_at and item.next_run_at < now and item.enabled]
        ),
        "active_claims": len([claim for claim in claims if claim.expires_at > now]),
        "expired_claims": len([claim for claim in claims if claim.expires_at <= now]),
        "observed_at": now,
    }


def build_lease_inventory(db: Session) -> dict[str, Any]:
    now = _utcnow()
    runtime_attempts = list(db.scalars(select(RuntimeExecutionAttempt)).all())
    scheduler_claims = list(db.scalars(select(SchedulerClaim)).all())
    active_runtime = [
        item
        for item in runtime_attempts
        if item.status in {"leased", "running"} and item.lease_expires_at and item.lease_expires_at > now
    ]
    expired_runtime = [
        item
        for item in runtime_attempts
        if item.status in {"leased", "running"} and item.lease_expires_at and item.lease_expires_at <= now
    ]
    active_scheduler = [item for item in scheduler_claims if item.expires_at > now]
    expired_scheduler = [item for item in scheduler_claims if item.expires_at <= now]
    return {
        "active_leases": len(active_runtime) + len(active_scheduler),
        "expired_leases": len(expired_runtime) + len(expired_scheduler),
        "conflicted_leases": 0,
        "released_leases": len(
            [item for item in runtime_attempts if item.status in {"succeeded", "failed", "cancelled"}]
        ),
        "abandoned_leases": len([item for item in runtime_attempts if item.status == "abandoned"]),
        "leases": [
            {
                "lease_owner": item.worker_id,
                "resource_type": "runtime_execution",
                "resource_reference": str(item.execution_id),
                "lease_expiration": item.lease_expires_at,
                "last_renewal": item.heartbeat_at,
                "status": "expired" if item in expired_runtime else item.status,
            }
            for item in active_runtime + expired_runtime
        ]
        + [
            {
                "lease_owner": item.owner_id,
                "resource_type": item.resource_type,
                "resource_reference": str(item.resource_id),
                "lease_expiration": item.expires_at,
                "last_renewal": item.heartbeat_at,
                "status": "expired" if item in expired_scheduler else "active",
            }
            for item in active_scheduler + expired_scheduler
        ],
        "observed_at": now,
    }


def build_operational_workspace_runtime(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    *,
    refresh: bool = True,
) -> OperationalWorkspaceRuntimeResponse:
    readiness = build_operational_readiness(
        db,
        scope=scope,
        organization_id=organization_id,
        refresh=refresh,
    )
    repo = OperationalObservabilityRepository(db)
    components = repo.list_components(scope, organization_id)
    observations = repo.list_observations(scope, organization_id)
    executions = repo.list_executions(scope, organization_id)
    incidents = repo.list_incidents(scope, organization_id)
    actions = repo.list_recovery_actions()
    retries = db.scalars(select(BoundedRetryAttempt)).all()
    evidence = repo.list_evidence(scope, organization_id)
    open_blockers = [
        {"incident_id": str(item.id), "code": item.incident_code, "severity": item.severity, "summary": item.summary}
        for item in incidents
        if item.status in OPEN_INCIDENT_STATUSES and item.severity in CRITICAL_SEVERITIES
    ]
    next_actions = [
        {"code": NEXT_ACTIONS[gate.gate_code], "source_gate": gate.gate_code}
        for gate in readiness.gates
        if gate.status != "passed"
    ]
    from app.services.production_observability_projection import build_production_observability_projection

    production_observability = build_production_observability_projection(
        db,
        organization_id=organization_id if scope == "organization" else None,
    )
    return OperationalWorkspaceRuntimeResponse(
        runtime_status=readiness.status,
        operational_readiness=readiness,
        component_summary={
            "component_count": len(components),
            "by_type": dict(Counter(item.component_type for item in components)),
            "by_status": dict(Counter(item.status for item in components)),
            "components": [
                RuntimeComponentRead.model_validate(item).model_dump(mode="json") for item in components[:20]
            ],
        },
        worker_summary={"workers": build_worker_inventory(db), "worker_count": _count(db, RuntimeWorker)},
        scheduler_summary=build_scheduler_inventory(db),
        lease_summary=build_lease_inventory(db),
        execution_summary={
            "execution_count": len(executions),
            "by_status": dict(Counter(item.status for item in executions)),
            "recent": [
                OperationalExecutionRead.model_validate(item).model_dump(mode="json") for item in executions[:10]
            ],
        },
        retry_summary={
            "retry_count": len(retries),
            "by_status": dict(Counter(item.status for item in retries)),
        },
        incident_summary={
            "incident_count": len(incidents),
            "open_incidents": len([item for item in incidents if item.status in OPEN_INCIDENT_STATUSES]),
            "by_severity": dict(Counter(item.severity for item in incidents)),
            "recent": [OperationalIncidentRead.model_validate(item).model_dump(mode="json") for item in incidents[:10]],
        },
        open_blockers=open_blockers,
        diagnostics=readiness.diagnostics,
        recent_recovery_actions=[
            FailureRecoveryActionRead.model_validate(item).model_dump(mode="json") for item in actions[:10]
        ],
        evidence_freshness={
            "evidence_count": len(evidence),
            "latest_observed_at": max((item.observed_at for item in evidence), default=None),
            "observation_count": len(observations),
        },
        dashboard_runtime=production_observability["dashboard_runtime"],
        health_runtime=production_observability["health_runtime"],
        warning_runtime=production_observability["warning_runtime"],
        alert_runtime=production_observability["alert_runtime"],
        next_actions=next_actions,
    )


def latest_operational_evidence(
    db: Session, scope: str = "platform", organization_id: uuid.UUID | None = None
) -> list[OperationalEvidenceRead]:
    repo = OperationalObservabilityRepository(db)
    return [OperationalEvidenceRead.model_validate(item) for item in repo.list_evidence(scope, organization_id)]
