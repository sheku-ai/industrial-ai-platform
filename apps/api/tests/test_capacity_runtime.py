from __future__ import annotations

from app.models.capacity import (
    CapacityAcceptance,
    CapacityEvaluation,
    CapacityEvidence,
    CapacityFinding,
    CapacityProfile,
    CapacityRecommendation,
    HistoricalCapacityTrend,
    LoadTestExecution,
    LoadTestResult,
)
from app.schemas.capacity import CAPACITY_METRICS, CapacityProfileCreate, CapacityVector
from app.services.capacity_runtime import CAPACITY_GATE_CODES, capacity_evidence_is_stale, stable_hash
from app.services.production_acceptance_catalog import PRODUCTION_ACCEPTANCE_GATES


def test_capacity_domain_declares_all_persistent_entities() -> None:
    assert {model.__tablename__ for model in (
        CapacityProfile,
        CapacityEvaluation,
        LoadTestExecution,
        LoadTestResult,
        CapacityFinding,
        CapacityRecommendation,
        CapacityEvidence,
        HistoricalCapacityTrend,
        CapacityAcceptance,
    )} == {
        "capacity_profiles",
        "capacity_evaluations",
        "capacity_load_test_executions",
        "capacity_load_test_results",
        "capacity_findings",
        "capacity_recommendations",
        "capacity_evidence",
        "capacity_trends",
        "capacity_acceptance",
    }


def test_capacity_vector_requires_every_governed_capacity_dimension() -> None:
    values = {metric: 1.0 for metric in CAPACITY_METRICS}
    vector = CapacityVector.model_validate(values)
    profile = CapacityProfileCreate(
        scope="platform",
        profile_code="production-baseline",
        name="Production Baseline",
        version="1",
        configured_capacity=vector,
        target_capacity=vector,
    )

    assert set(profile.configured_capacity.model_dump()) == set(CAPACITY_METRICS)


def test_capacity_hash_is_deterministic() -> None:
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})


def test_production_acceptance_capacity_catalog_uses_only_persisted_runtime_gates() -> None:
    gates = [gate for gate in PRODUCTION_ACCEPTANCE_GATES if gate.domain == "capacity"]

    assert tuple(gate.gate_code for gate in gates) == CAPACITY_GATE_CODES
    assert all(gate.evidence_requirements == ("capacity_evidence_contract",) for gate in gates)
    assert all(gate.evaluation_strategy == "authoritative_evidence_contract" for gate in gates)


def test_capacity_models_are_postgresql_runtime_tables() -> None:
    assert all(
        model.__table__.schema == "runtime"
        for model in (
            CapacityProfile,
            CapacityEvaluation,
            LoadTestExecution,
            LoadTestResult,
            CapacityFinding,
            CapacityRecommendation,
            CapacityEvidence,
            HistoricalCapacityTrend,
            CapacityAcceptance,
        )
    )


def test_capacity_freshness_uses_persisted_profile_policy() -> None:
    profile = type("Profile", (), {"evidence_max_age_hours": 24})()
    assert capacity_evidence_is_stale(profile, 24 * 3600) is False
    assert capacity_evidence_is_stale(profile, 24 * 3600 + 1) is True
