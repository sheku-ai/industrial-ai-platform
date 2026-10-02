from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
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
from app.repositories.capacity import CapacityRepository
from app.schemas.capacity import (
    CAPACITY_METRICS,
    CapacityAcceptanceRead,
    CapacityEvaluationRead,
    CapacityEvaluationRequest,
    CapacityEvidenceCreate,
    CapacityEvidenceRead,
    CapacityGateResult,
    CapacityLatestResponse,
    CapacityProfileCreate,
    CapacityProfileRead,
    CapacityReadinessResponse,
    CapacityRecommendationRead,
    CapacityTrendRead,
    LoadTestExecutionComplete,
    LoadTestExecutionCreate,
    LoadTestExecutionRead,
    LoadTestResultCreate,
    LoadTestResultRead,
)
from app.services.readiness_contract import build_readiness_evidence

CAPACITY_GATE_CODES = (
    "capacity_profile_defined",
    "load_test_completed",
    "capacity_validated",
    "capacity_bottlenecks_resolved",
    "production_capacity_ready",
)


def capacity_evidence_is_stale(profile: CapacityProfile | None, evidence_age_seconds: int | None) -> bool:
    return bool(
        profile and evidence_age_seconds is not None and evidence_age_seconds > profile.evidence_max_age_hours * 3600
    )


def _now() -> datetime:
    return datetime.now(UTC)


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _vector(payload: Any) -> dict[str, float]:
    source = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    return {metric: float(source.get(metric) or 0) for metric in CAPACITY_METRICS}


def _audit(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    resource_type: str,
    resource_id: uuid.UUID,
    action: str,
    actor_id: str | None,
    correlation_id: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    metadata = {"action": action, "correlation_id": correlation_id, "postgresql_source_of_truth": True}
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_type="service",
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            summary=f"capacity runtime: {action}",
            metadata_json=metadata,
        )
    )
    db.add(
        AuditHistory(
            organization_id=organization_id,
            entity_type=resource_type,
            entity_id=str(resource_id),
            action=action,
            before_state=before or {},
            after_state={**(after or {}), **metadata},
            actor_type="service",
            actor_id=actor_id,
        )
    )


def create_capacity_profile(db: Session, payload: CapacityProfileCreate) -> CapacityProfileRead:
    repo = CapacityRepository(db)
    profile_payload = payload.model_dump(mode="json", exclude={"created_by"})
    existing = repo.find_profile(
        payload.scope,
        payload.organization_id,
        payload.profile_code,
        payload.version,
    )
    if existing is not None:
        persisted_payload = {
            "scope": existing.scope,
            "organization_id": existing.organization_id,
            "profile_code": existing.profile_code,
            "name": existing.name,
            "description": existing.description,
            "version": existing.version,
            "status": existing.status,
            "configured_capacity": existing.configured_capacity,
            "target_capacity": existing.target_capacity,
            "thresholds": existing.thresholds,
            "evidence_max_age_hours": existing.evidence_max_age_hours,
        }
        if stable_hash(persisted_payload) != stable_hash(profile_payload):
            raise ValueError("capacity_profile_conflict")
        return CapacityProfileRead.model_validate(existing)
    if payload.status == "active":
        for deactivated in repo.deactivate_profiles(payload.scope, payload.organization_id):
            _audit(
                db,
                organization_id=deactivated.organization_id,
                resource_type="runtime.capacity_profile",
                resource_id=deactivated.id,
                action="deactivated",
                actor_id=payload.created_by,
                correlation_id=None,
                before={"status": "active"},
                after={"status": "inactive"},
            )
    now = _now()
    row = repo.add(
        CapacityProfile(
            organization_id=payload.organization_id,
            scope=payload.scope,
            profile_code=payload.profile_code,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            status=payload.status,
            configured_capacity=_vector(payload.configured_capacity),
            target_capacity=_vector(payload.target_capacity),
            thresholds=payload.thresholds,
            evidence_max_age_hours=payload.evidence_max_age_hours,
            created_by=payload.created_by,
            activated_at=now if payload.status == "active" else None,
        )
    )
    _audit(
        db,
        organization_id=row.organization_id,
        resource_type="runtime.capacity_profile",
        resource_id=row.id,
        action="created",
        actor_id=payload.created_by,
        correlation_id=None,
        after={"profile_code": row.profile_code, "version": row.version, "status": row.status},
    )
    return CapacityProfileRead.model_validate(row)


def register_load_test(db: Session, payload: LoadTestExecutionCreate) -> LoadTestExecutionRead:
    repo = CapacityRepository(db)
    profile = repo.get_profile(payload.profile_id, payload.scope, payload.organization_id)
    if profile is None:
        raise ValueError("capacity_profile_not_found")
    input_payload = payload.model_dump(mode="json", exclude={"correlation_id"})
    input_hash = stable_hash(input_payload)
    existing = repo.find_load_test(payload.scope, payload.organization_id, payload.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("idempotency_key_conflict")
        return LoadTestExecutionRead.model_validate(existing)
    row = repo.add(
        LoadTestExecution(
            profile_id=profile.id,
            organization_id=payload.organization_id,
            scope=payload.scope,
            execution_name=payload.execution_name,
            scenario=payload.scenario,
            status="running",
            concurrent_requests=payload.concurrent_requests,
            duration_seconds=payload.duration_seconds,
            requests_planned=payload.requests_planned,
            idempotency_key=payload.idempotency_key,
            input_hash=input_hash,
            correlation_id=payload.correlation_id or f"capacity-load:{uuid.uuid4()}",
            requested_by=payload.requested_by,
            started_at=_now(),
            execution_metadata=payload.execution_metadata,
        )
    )
    _audit(
        db,
        organization_id=row.organization_id,
        resource_type="runtime.capacity_load_test",
        resource_id=row.id,
        action="registered",
        actor_id=row.requested_by,
        correlation_id=row.correlation_id,
        after=input_payload,
    )
    return LoadTestExecutionRead.model_validate(row)


def register_load_test_result(
    db: Session, execution: LoadTestExecution, payload: LoadTestResultCreate
) -> LoadTestResultRead:
    repo = CapacityRepository(db)
    result_payload = payload.model_dump(mode="json")
    existing = repo.find_result(execution.id, payload.metric_code)
    if existing is not None:
        existing_hash = stable_hash(
            {
                "metric_code": existing.metric_code,
                "component": existing.component,
                "observed_value": float(existing.observed_value),
                "target_value": float(existing.target_value),
                "unit": existing.unit,
                "sample_count": existing.sample_count,
                "percentile_values": existing.percentile_values,
                "details": existing.details,
                "observed_at": existing.observed_at,
            }
        )
        if existing_hash != stable_hash(result_payload):
            raise ValueError("load_test_result_conflict")
        return LoadTestResultRead.model_validate(existing)
    if execution.status != "running":
        raise ValueError("load_test_not_running")
    row = repo.add(
        LoadTestResult(
            load_test_execution_id=execution.id,
            metric_code=payload.metric_code,
            component=payload.component,
            observed_value=payload.observed_value,
            target_value=payload.target_value,
            unit=payload.unit,
            passed=payload.observed_value >= payload.target_value,
            sample_count=payload.sample_count,
            percentile_values=payload.percentile_values,
            details=payload.details,
            observed_at=payload.observed_at,
        )
    )
    _audit(
        db,
        organization_id=execution.organization_id,
        resource_type="runtime.capacity_load_test_result",
        resource_id=row.id,
        action="recorded",
        actor_id=execution.requested_by,
        correlation_id=execution.correlation_id,
        after=result_payload,
    )
    return LoadTestResultRead.model_validate(row)


def complete_load_test(
    db: Session, execution: LoadTestExecution, payload: LoadTestExecutionComplete
) -> LoadTestExecutionRead:
    if execution.status in {"completed", "failed", "blocked", "cancelled"}:
        metadata_matches = all(
            execution.execution_metadata.get(key) == value for key, value in payload.result_metadata.items()
        )
        if (
            execution.status == payload.status
            and execution.requests_completed == payload.requests_completed
            and execution.requests_failed == payload.requests_failed
            and metadata_matches
        ):
            return LoadTestExecutionRead.model_validate(execution)
        raise ValueError("load_test_completion_conflict")
    before = {"status": execution.status}
    results = CapacityRepository(db).list_results(execution.id)
    execution.status = payload.status
    execution.requests_completed = payload.requests_completed
    execution.requests_failed = payload.requests_failed
    execution.completed_at = _now()
    execution.execution_metadata = {**execution.execution_metadata, **payload.result_metadata}
    execution.result_hash = stable_hash(
        {
            "execution_id": execution.id,
            "status": execution.status,
            "requests_completed": execution.requests_completed,
            "requests_failed": execution.requests_failed,
            "results": [LoadTestResultRead.model_validate(item).model_dump(mode="json") for item in results],
        }
    )
    _audit(
        db,
        organization_id=execution.organization_id,
        resource_type="runtime.capacity_load_test",
        resource_id=execution.id,
        action="completed",
        actor_id=execution.requested_by,
        correlation_id=execution.correlation_id,
        before=before,
        after={"status": execution.status, "result_hash": execution.result_hash},
    )
    db.flush()
    return LoadTestExecutionRead.model_validate(execution)


def evaluate_capacity(db: Session, request: CapacityEvaluationRequest) -> CapacityEvaluationRead:
    repo = CapacityRepository(db)
    profile = repo.get_profile(request.profile_id, request.scope, request.organization_id)
    execution = repo.get_load_test(request.load_test_execution_id, request.scope, request.organization_id)
    if profile is None:
        raise ValueError("capacity_profile_not_found")
    if execution is None or execution.profile_id != profile.id:
        raise ValueError("load_test_execution_not_found")
    results = repo.list_results(execution.id)
    input_hash = stable_hash(
        {
            "profile_id": profile.id,
            "profile_updated_at": profile.updated_at,
            "load_test_execution_id": execution.id,
            "load_test_result_hash": execution.result_hash,
        }
    )
    existing = repo.find_evaluation(request.scope, request.organization_id, request.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("idempotency_key_conflict")
        return CapacityEvaluationRead.model_validate(existing)

    configured = _vector(profile.configured_capacity)
    target = _vector(profile.target_capacity)
    result_by_metric = {item.metric_code: item for item in results}
    observed = {
        metric: float(result_by_metric[metric].observed_value) if metric in result_by_metric else 0.0
        for metric in CAPACITY_METRICS
    }
    utilization = {
        metric: round(observed[metric] / configured[metric], 6) if configured[metric] > 0 else 0.0
        for metric in CAPACITY_METRICS
    }
    bottlenecks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for metric in CAPACITY_METRICS:
        if metric not in result_by_metric:
            issue = {"code": f"{metric}_evidence_missing", "component": metric, "severity": "blocking"}
            blockers.append(issue)
            next_actions.append({"action": f"record_{metric}_capacity_evidence", "component": metric})
        elif observed[metric] < target[metric]:
            issue = {
                "code": f"{metric}_capacity_below_target",
                "component": metric,
                "severity": "blocking",
                "observed": observed[metric],
                "target": target[metric],
            }
            bottlenecks.append(issue)
            blockers.append(issue)
            recommendations.append(
                {
                    "code": f"increase_{metric}_capacity",
                    "component": metric,
                    "priority": "high",
                    "summary": f"Increase {metric} capacity to meet the persisted target.",
                    "recommended_action": f"Resolve the {metric} bottleneck and execute a new governed load test.",
                }
            )
            next_actions.append({"action": f"resolve_{metric}_capacity", "component": metric})
        elif configured[metric] and observed[metric] < configured[metric]:
            warnings.append(
                {
                    "code": f"{metric}_below_configured_capacity",
                    "component": metric,
                    "observed": observed[metric],
                    "configured": configured[metric],
                }
            )
    if execution.status != "completed":
        blockers.append({"code": "load_test_not_completed", "component": "load_test", "severity": "blocking"})
        next_actions.append({"action": "complete_load_test", "component": "load_test"})

    evaluated_at = _now()
    evidence_observed_at = max((item.observed_at for item in results), default=None)
    evidence_age_seconds = (
        max(0, int((evaluated_at - evidence_observed_at).total_seconds())) if evidence_observed_at else None
    )
    result_payload = {
        "configured_capacity": configured,
        "observed_capacity": observed,
        "target_capacity": target,
        "utilization": utilization,
        "bottlenecks": bottlenecks,
        "blockers": blockers,
        "warnings": warnings,
        "recommendations": recommendations,
        "next_actions": next_actions,
        "load_test_result_ids": [str(item.id) for item in results],
    }
    evaluation = repo.add(
        CapacityEvaluation(
            profile_id=profile.id,
            load_test_execution_id=execution.id,
            organization_id=request.organization_id,
            scope=request.scope,
            status="passed" if not blockers else "blocked",
            configured_capacity=configured,
            observed_capacity=observed,
            target_capacity=target,
            utilization=utilization,
            bottlenecks=bottlenecks,
            blockers=blockers,
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions,
            idempotency_key=request.idempotency_key,
            input_hash=input_hash,
            result_hash=stable_hash(result_payload),
            correlation_id=request.correlation_id or f"capacity-evaluation:{uuid.uuid4()}",
            requested_by=request.requested_by,
            evidence_observed_at=evidence_observed_at,
            evidence_age_seconds=evidence_age_seconds,
            evaluated_at=evaluated_at,
        )
    )
    finding_by_component: dict[str, CapacityFinding] = {}
    for issue in blockers:
        component = str(issue["component"])
        finding = repo.add(
            CapacityFinding(
                evaluation_id=evaluation.id,
                finding_code=str(issue["code"]),
                finding_type="bottleneck" if "below_target" in str(issue["code"]) else "missing_evidence",
                severity="blocking",
                status="open",
                component=component,
                summary=str(issue["code"]).replace("_", " ").capitalize(),
                details=issue,
            )
        )
        finding_by_component[component] = finding
    for recommendation in recommendations:
        repo.add(
            CapacityRecommendation(
                evaluation_id=evaluation.id,
                finding_id=finding_by_component.get(str(recommendation["component"])).id
                if finding_by_component.get(str(recommendation["component"]))
                else None,
                recommendation_code=str(recommendation["code"]),
                priority=str(recommendation["priority"]),
                status="open",
                component=str(recommendation["component"]),
                summary=str(recommendation["summary"]),
                recommended_action=str(recommendation["recommended_action"]),
                details=recommendation,
            )
        )
    for metric in CAPACITY_METRICS:
        repo.add(
            HistoricalCapacityTrend(
                evaluation_id=evaluation.id,
                organization_id=evaluation.organization_id,
                scope=evaluation.scope,
                metric_code=metric,
                observed_value=observed[metric],
                configured_value=configured[metric],
                target_value=target[metric],
                utilization_ratio=utilization[metric],
                status="passed" if observed[metric] >= target[metric] else "blocked",
                captured_at=evaluated_at,
            )
        )
    evidence_payload = {
        "load_test_execution_id": str(execution.id),
        "load_test_result_ids": [str(item.id) for item in results],
        "execution_result_hash": execution.result_hash,
        "observed_capacity": observed,
    }
    evidence = repo.add(
        CapacityEvidence(
            evaluation_id=evaluation.id,
            load_test_execution_id=execution.id,
            evidence_code="governed_load_test_results",
            evidence_type="load_test_results",
            source_runtime="capacity_load_test_runtime",
            source_reference=str(execution.id),
            evidence_payload=evidence_payload,
            evidence_hash=stable_hash(evidence_payload),
            observed_at=evidence_observed_at or evaluated_at,
        )
    )
    _persist_acceptance(db, profile, evaluation, execution, results, [evidence])
    _audit(
        db,
        organization_id=evaluation.organization_id,
        resource_type="runtime.capacity_evaluation",
        resource_id=evaluation.id,
        action="evaluated",
        actor_id=evaluation.requested_by,
        correlation_id=evaluation.correlation_id,
        after={"status": evaluation.status, "result_hash": evaluation.result_hash},
    )
    return CapacityEvaluationRead.model_validate(evaluation)


def register_capacity_evidence(
    db: Session, evaluation: CapacityEvaluation, payload: CapacityEvidenceCreate
) -> CapacityEvidenceRead:
    repo = CapacityRepository(db)
    evidence_hash = stable_hash(payload.evidence_payload)
    existing = repo.find_evidence(evaluation.id, payload.evidence_code, evidence_hash)
    if existing is not None:
        return CapacityEvidenceRead.model_validate(existing)
    row = repo.add(
        CapacityEvidence(
            evaluation_id=evaluation.id,
            load_test_execution_id=evaluation.load_test_execution_id,
            evidence_code=payload.evidence_code,
            evidence_type=payload.evidence_type,
            source_runtime=payload.source_runtime,
            source_reference=payload.source_reference,
            evidence_payload=payload.evidence_payload,
            evidence_hash=evidence_hash,
            observed_at=payload.observed_at,
        )
    )
    _audit(
        db,
        organization_id=evaluation.organization_id,
        resource_type="runtime.capacity_evidence",
        resource_id=row.id,
        action="recorded",
        actor_id=evaluation.requested_by,
        correlation_id=evaluation.correlation_id,
        after={"evidence_code": row.evidence_code, "evidence_hash": row.evidence_hash},
    )
    profile = repo.get_profile(evaluation.profile_id, evaluation.scope, evaluation.organization_id)
    execution = repo.get_load_test(
        evaluation.load_test_execution_id,
        evaluation.scope,
        evaluation.organization_id,
    )
    if profile is None or execution is None:
        raise ValueError("capacity_evaluation_sources_not_found")
    evidence = repo.evidence(evaluation.id)
    _persist_acceptance(
        db,
        profile,
        evaluation,
        execution,
        repo.list_results(execution.id),
        evidence,
    )
    return CapacityEvidenceRead.model_validate(row)


def _persist_acceptance(
    db: Session,
    profile: CapacityProfile,
    evaluation: CapacityEvaluation,
    execution: LoadTestExecution,
    results: list[LoadTestResult],
    evidence: list[CapacityEvidence],
) -> CapacityAcceptance:
    repo = CapacityRepository(db)
    governed_evidence = [
        item
        for item in evidence
        if item.evidence_type == "load_test_results" and item.load_test_execution_id == execution.id
    ]
    profile_defined = profile.status == "active" and all(
        metric in profile.target_capacity for metric in CAPACITY_METRICS
    )
    load_completed = execution.status == "completed" and len({item.metric_code for item in results}) == len(
        CAPACITY_METRICS
    )
    capacity_validated = bool(governed_evidence) and all(
        float(evaluation.observed_capacity.get(metric) or 0) >= float(evaluation.target_capacity.get(metric) or 0)
        for metric in CAPACITY_METRICS
    )
    bottlenecks_resolved = not any(
        finding.status in {"open", "acknowledged"} and finding.severity in {"blocking", "critical"}
        for finding in repo.findings(evaluation.id)
    )
    ready = profile_defined and load_completed and capacity_validated and bottlenecks_resolved
    evidence_reference = str(governed_evidence[0].id) if governed_evidence else None
    conditions = (
        ("capacity_profile_defined", profile_defined, str(profile.id)),
        ("load_test_completed", load_completed, str(execution.id)),
        ("capacity_validated", capacity_validated, evidence_reference),
        ("capacity_bottlenecks_resolved", bottlenecks_resolved, str(evaluation.id)),
        ("production_capacity_ready", ready, str(evaluation.id)),
    )
    gates = [
        {
            "gate_code": code,
            "status": "passed" if passed else "blocked",
            "evidence_reference": reference,
            "summary": (
                f"{code.replace('_', ' ').capitalize()} is "
                f"{'satisfied' if passed else 'not satisfied'} by persisted capacity evidence."
            ),
        }
        for code, passed, reference in conditions
    ]
    latest_observed = max((item.observed_at for item in governed_evidence), default=None)
    evidence_age = max(0, int((_now() - latest_observed).total_seconds())) if latest_observed else None
    acceptance = repo.acceptance(evaluation.id)
    payload = {
        "evaluation_id": str(evaluation.id),
        "gate_results": gates,
        "evidence_ids": [str(item.id) for item in evidence],
    }
    created = acceptance is None
    if created:
        acceptance = CapacityAcceptance(
            evaluation_id=evaluation.id,
            profile_id=profile.id,
            organization_id=evaluation.organization_id,
            scope=evaluation.scope,
            accepted_by=evaluation.requested_by,
            accepted_at=_now(),
        )
        db.add(acceptance)
    acceptance.status = "passed" if ready else "blocked"
    acceptance.gate_results = gates
    acceptance.blocker_count = len(evaluation.blockers)
    acceptance.recommendation_count = len(evaluation.recommendations)
    acceptance.evidence_age_seconds = evidence_age
    acceptance.result_hash = stable_hash(payload)
    db.flush()
    _audit(
        db,
        organization_id=acceptance.organization_id,
        resource_type="runtime.capacity_acceptance",
        resource_id=acceptance.id,
        action="created" if created else "recomputed",
        actor_id=acceptance.accepted_by,
        correlation_id=evaluation.correlation_id,
        after={
            "status": acceptance.status,
            "gate_results": acceptance.gate_results,
            "result_hash": acceptance.result_hash,
        },
    )
    return acceptance


def build_capacity_readiness(
    db: Session, *, scope: str = "platform", organization_id: uuid.UUID | None = None
) -> CapacityReadinessResponse:
    repo = CapacityRepository(db)
    profile = repo.active_profile(scope, organization_id)
    evaluation = repo.latest_evaluation(scope, organization_id, profile.id) if profile else None
    acceptance = repo.acceptance(evaluation.id) if evaluation else None
    recommendations = repo.recommendations(evaluation.id) if evaluation else []
    evidence_by_code: dict[str, CapacityEvidence] = {}
    for item in repo.evidence(evaluation.id) if evaluation else []:
        evidence_by_code.setdefault(item.evidence_code, item)
    evidence = list(evidence_by_code.values())
    governed_evidence = [item for item in evidence if item.evidence_type == "load_test_results"]
    latest_observed = max((item.observed_at for item in governed_evidence), default=None)
    evidence_age = max(0, int((_now() - latest_observed).total_seconds())) if latest_observed else None
    evidence_stale = capacity_evidence_is_stale(profile, evidence_age)
    blockers = list(evaluation.blockers) if evaluation else [{"code": "capacity_evaluation_missing"}]
    if profile is None:
        blockers.insert(0, {"code": "capacity_profile_missing"})
    if evidence_stale:
        blockers.append({"code": "capacity_evidence_stale", "evidence_age_seconds": evidence_age})
    status = (
        "passed"
        if acceptance and acceptance.status == "passed" and not evidence_stale
        else "blocked"
        if evaluation or profile
        else "not_evaluated"
    )
    gate_results = (
        list(acceptance.gate_results)
        if acceptance
        else [
            {
                "gate_code": gate_code,
                "status": "not_evaluated",
                "summary": "Persisted capacity evidence is not available.",
                "evidence_reference": None,
            }
            for gate_code in (
                "capacity_profile_defined",
                "load_test_completed",
                "capacity_validated",
                "capacity_bottlenecks_resolved",
                "production_capacity_ready",
            )
        ]
    )
    if evidence_stale:
        gate_results = [
            {
                **item,
                "status": "blocked",
                "summary": "Persisted capacity evidence exceeds the active profile freshness policy.",
            }
            if item.get("gate_code") in {"capacity_validated", "production_capacity_ready"}
            else item
            for item in gate_results
        ]
    warnings = list(evaluation.warnings) if evaluation else []
    next_actions = list(evaluation.next_actions) if evaluation else [{"action": "execute_capacity_evaluation"}]
    recommendation_payloads = [
        CapacityRecommendationRead.model_validate(item).model_dump(mode="json") for item in recommendations
    ]
    integrity_errors = [
        {
            "code": "capacity_evidence_corrupt",
            "message": "Persisted capacity evidence hash does not match its payload.",
            "evidence_id": str(item.id),
        }
        for item in evidence
        if stable_hash(item.evidence_payload) != item.evidence_hash
    ]
    evidence_contract = build_readiness_evidence(
        domain="capacity",
        status="stale" if evidence_stale else status,
        gate_results=gate_results,
        blockers=blockers,
        warnings=warnings,
        recommendations=recommendation_payloads,
        next_actions=next_actions,
        runtime_version="capacity-load-evidence-runtime.v1",
        evaluation_timestamp=evaluation.evaluated_at if evaluation else None,
        expires_at=(latest_observed + timedelta(hours=profile.evidence_max_age_hours))
        if latest_observed and profile
        else None,
        evidence_origin="capacity_load_evidence_runtime",
        components_evaluated=list(evaluation.observed_capacity.keys()) if evaluation else [],
        evidence_ids=[str(item.id) for item in evidence],
        source_runtime_version="capacity-load-evidence-runtime.v1",
        supported_runtime_versions=("capacity-load-evidence-runtime.v1",),
        integrity_errors=integrity_errors,
    )
    return CapacityReadinessResponse(
        evidence_contract=evidence_contract,
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        scope=scope,
        organization_id=organization_id,
        active_profile=CapacityProfileRead.model_validate(profile) if profile else None,
        latest_evaluation=CapacityEvaluationRead.model_validate(evaluation) if evaluation else None,
        latest_acceptance=CapacityAcceptanceRead.model_validate(acceptance) if acceptance else None,
        configured_capacity=evaluation.configured_capacity
        if evaluation
        else (profile.configured_capacity if profile else None),
        observed_capacity=evaluation.observed_capacity if evaluation else None,
        target_capacity=evaluation.target_capacity if evaluation else (profile.target_capacity if profile else None),
        utilization=evaluation.utilization if evaluation else None,
        bottlenecks=list(evaluation.bottlenecks) if evaluation else [],
        blockers=evidence_contract.blockers,
        warnings=evidence_contract.warnings,
        recommendations=evidence_contract.recommendations,
        next_actions=evidence_contract.next_actions,
        blocker_count=len(evidence_contract.blockers),
        recommendation_count=len(evidence_contract.recommendations),
        evidence_age_seconds=evidence_age,
        evidence_age_hours=round(evidence_age / 3600, 2) if evidence_age is not None else None,
        gate_results=[CapacityGateResult.model_validate(item) for item in gate_results],
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
    )


def latest_capacity_result(
    db: Session, *, scope: str = "platform", organization_id: uuid.UUID | None = None
) -> CapacityLatestResponse:
    repo = CapacityRepository(db)
    evaluation = repo.latest_evaluation(scope, organization_id)
    if evaluation is None:
        return CapacityLatestResponse(found=False)
    execution = (
        repo.get_load_test(evaluation.load_test_execution_id, scope, organization_id)
        if evaluation.load_test_execution_id
        else None
    )
    return CapacityLatestResponse(
        found=True,
        evaluation=CapacityEvaluationRead.model_validate(evaluation),
        acceptance=CapacityAcceptanceRead.model_validate(repo.acceptance(evaluation.id)),
        load_test_execution=LoadTestExecutionRead.model_validate(execution) if execution else None,
        results=[LoadTestResultRead.model_validate(item) for item in repo.list_results(execution.id)]
        if execution
        else [],
    )


def capacity_history(
    db: Session, *, scope: str, organization_id: uuid.UUID | None, limit: int = 500
) -> list[CapacityTrendRead]:
    return [
        CapacityTrendRead.model_validate(item) for item in CapacityRepository(db).trends(scope, organization_id, limit)
    ]
