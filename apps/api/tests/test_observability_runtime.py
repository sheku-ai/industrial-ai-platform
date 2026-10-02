from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import observability as models
from app.schemas.observability import HeartbeatCreate, ObservabilityProfileCreate
from app.services.observability_runtime import (
    OBSERVABILITY_GATE_CODES,
    build_observability_readiness,
    stable_hash,
)
from app.services.production_acceptance_catalog import PRODUCTION_ACCEPTANCE_GATES
from app.services.production_readiness_runtime import build_production_readiness_runtime


def test_observability_domain_declares_complete_persistent_model() -> None:
    expected = {
        "observability_profiles",
        "observability_health_domains",
        "observability_components",
        "observability_dependencies",
        "observability_signals",
        "observability_heartbeats",
        "observability_availability_windows",
        "observability_health_evaluations",
        "observability_health_findings",
        "observability_health_evidence",
        "observability_health_acceptance",
        "observability_health_history",
    }
    declared = {
        value.__table__.name
        for value in vars(models).values()
        if isinstance(value, type) and hasattr(value, "__table__")
    }
    assert expected <= declared
    assert all(
        value.__table__.schema == "runtime"
        for value in vars(models).values()
        if isinstance(value, type) and hasattr(value, "__table__")
    )


def test_observability_evidence_contains_required_provenance_fields() -> None:
    columns = set(models.HealthEvidence.__table__.columns.keys())
    assert {
        "origin",
        "source",
        "contract_version",
        "runtime_version",
        "evaluation_timestamp",
        "expires_at",
        "component_ids",
        "dependency_ids",
        "heartbeat_ids",
        "signal_ids",
        "finding_ids",
    } <= columns


def test_scope_contract_rejects_mixed_platform_and_organization() -> None:
    with pytest.raises(ValidationError, match="must be omitted"):
        ObservabilityProfileCreate(
            scope="platform",
            organization_id=uuid.uuid4(),
            profile_code="production-health",
            name="Production Health",
            version="1",
        )


def test_heartbeat_expiration_must_follow_observation() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="later than observed_at"):
        HeartbeatCreate(
            component_id=uuid.uuid4(),
            status="healthy",
            origin="smoke",
            source="test",
            idempotency_key="heartbeat-1",
            observed_at=now,
            expires_at=now - timedelta(seconds=1),
        )


def test_hash_is_deterministic_for_idempotency() -> None:
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})


def test_production_acceptance_catalog_contains_only_required_observability_gates() -> None:
    actual = {gate.gate_code for gate in PRODUCTION_ACCEPTANCE_GATES if gate.gate_code.startswith("observability_")}
    assert actual == set(OBSERVABILITY_GATE_CODES)
    assert all(gate.domain == "operational" for gate in PRODUCTION_ACCEPTANCE_GATES if gate.gate_code in actual)


def test_readiness_is_a_read_only_postgresql_projection() -> None:
    source = inspect.getsource(build_observability_readiness)
    assert "get_settings" not in source
    assert "cache" not in source
    assert "requests" not in source
    assert ".add(" not in source
    assert ".flush(" not in source


def test_production_readiness_consumes_persisted_production_acceptance_not_operations_aggregate() -> None:
    source = inspect.getsource(build_production_readiness_runtime)
    assert "get_latest_production_acceptance" in source
    assert "build_operations_center_runtime" not in source
