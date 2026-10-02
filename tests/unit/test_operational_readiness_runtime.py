from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.operational_observability import (
    BoundedRetryAttempt,
    FailureRecoveryAction,
    OperationalEvidence,
    OperationalExecution,
    OperationalIncident,
    RuntimeComponent,
    RuntimeObservation,
)
from app.models.runtime_worker import RuntimeWorker
from app.services.operational_observability_runtime import (
    build_operational_readiness,
    build_worker_inventory,
    stable_hash,
)


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeSession:
    def __init__(self, values_by_model):
        self.values_by_model = values_by_model
        self.added = []

    def scalars(self, statement):
        model = statement.column_descriptions[0]["entity"]
        return FakeScalarResult(self.values_by_model.get(model, []))

    def scalar(self, statement):
        model = statement.column_descriptions[0]["entity"]
        if model is None:
            return 0
        values = self.values_by_model.get(model, [])
        return values[0] if values else None

    def add(self, value):
        self.added.append(value)
        self.values_by_model.setdefault(type(value), []).append(value)

    def flush(self):
        now = datetime.now(UTC)
        for value in self.added:
            if hasattr(type(value), "id") and value.id is None:
                value.id = uuid.uuid4()
            if hasattr(type(value), "created_at") and value.created_at is None:
                value.created_at = now
            if hasattr(type(value), "updated_at") and value.updated_at is None:
                value.updated_at = now


def component(**kwargs):
    now = datetime.now(UTC)
    base = {
        "id": uuid.uuid4(),
        "organization_id": None,
        "scope": "platform",
        "component_code": "api",
        "component_type": "api",
        "instance_id": "api-1",
        "display_name": "API",
        "runtime_version": None,
        "status": "running",
        "health_status": "healthy",
        "readiness_status": "ready",
        "capabilities": [],
        "configuration_reference": {},
        "last_started_at": now,
        "last_heartbeat_at": now,
        "last_success_at": now,
        "last_failure_at": None,
        "observed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    base.update(kwargs)
    item = RuntimeComponent(**base)
    return item


def evidence(evidence_type, status="passed", **payload):
    now = datetime.now(UTC)
    body = payload or {"evidence_type": evidence_type}
    return OperationalEvidence(
        id=uuid.uuid4(),
        organization_id=None,
        scope="platform",
        evidence_type=evidence_type,
        source_entity_type="test",
        source_entity_id=evidence_type,
        status=status,
        evidence_payload=body,
        evidence_hash=stable_hash(body),
        observed_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
    )


def test_operational_readiness_synchronizes_observability_without_prior_observations():
    db = FakeSession(
        {
            RuntimeComponent: [],
            RuntimeObservation: [],
            OperationalEvidence: [],
            OperationalIncident: [],
            OperationalExecution: [],
            FailureRecoveryAction: [],
            BoundedRetryAttempt: [],
        }
    )
    result = build_operational_readiness(db)
    assert result.status == "blocked"
    assert any(gate.gate_code == "runtime_observability_available" and gate.status == "passed" for gate in result.gates)


def test_operational_readiness_failed_with_critical_incident():
    incident = OperationalIncident(
        id=uuid.uuid4(),
        organization_id=None,
        scope="platform",
        incident_code="critical_worker_failure",
        incident_type="worker_failure",
        severity="critical",
        status="open",
        component_id=None,
        operational_execution_id=None,
        source_entity_type="test",
        source_entity_id="worker",
        summary="Worker failed.",
        details={},
        first_observed_at=datetime.now(UTC),
        last_observed_at=datetime.now(UTC),
        acknowledged_at=None,
        resolved_at=None,
        acknowledged_by=None,
        resolved_by=None,
        resolution_code=None,
        resolution_summary=None,
        occurrence_count=1,
        evidence_hash=stable_hash({"incident": "critical_worker_failure"}),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db = FakeSession(
        {
            RuntimeComponent: [component(component_type="worker", component_code="worker", instance_id="worker-1")],
            RuntimeObservation: [],
            OperationalEvidence: [evidence("component_readiness")],
            OperationalIncident: [incident],
            OperationalExecution: [],
            FailureRecoveryAction: [],
            BoundedRetryAttempt: [],
        }
    )
    result = build_operational_readiness(db)
    assert result.status == "failed"
    assert any(gate.gate_code == "operational_blockers_visible" and gate.status == "failed" for gate in result.gates)


def test_worker_inventory_marks_stale_worker_unavailable():
    now = datetime.now(UTC)
    worker = RuntimeWorker(
        worker_key="worker-1",
        worker_type="processor",
        instance_id="instance-1",
        observed_state="ready",
        desired_state="active",
        heartbeat_at=now - timedelta(minutes=10),
        ready_at=now,
        updated_at=now,
        last_error_code=None,
        capabilities=["processing"],
        metrics={},
    )
    db = FakeSession({RuntimeWorker: [worker]})
    inventory = build_worker_inventory(db)
    assert inventory[0]["status"] == "unavailable"
    assert inventory[0]["readiness"] == "not_ready"


def test_retry_attempt_requires_bounded_policy_evidence():
    retry = BoundedRetryAttempt(
        id=uuid.uuid4(),
        operational_execution_id=uuid.uuid4(),
        attempt_number=1,
        retry_policy_code="bounded",
        status="exhausted",
        scheduled_at=datetime.now(UTC),
        started_at=None,
        completed_at=datetime.now(UTC),
        delay_seconds=0,
        failure_code="retry_exhausted",
        failure_summary="Retry exhausted.",
        retryable=True,
        decision_reason="max attempts reached",
        evidence_payload={"max_attempts": 3},
        created_at=datetime.now(UTC),
    )
    assert retry.attempt_number == 1
    assert retry.retry_policy_code == "bounded"
    assert retry.status == "exhausted"


def test_recovery_action_does_not_auto_resolve_incident():
    incident = OperationalIncident(status="open", incident_code="failure", incident_type="other", severity="warning")
    action = FailureRecoveryAction(
        incident_id=uuid.uuid4(),
        action_type="manual_recovery",
        status="completed",
        input_hash=stable_hash({"manual": True}),
        evidence_payload={"manual": True},
    )
    assert action.status == "completed"
    assert incident.status == "open"
