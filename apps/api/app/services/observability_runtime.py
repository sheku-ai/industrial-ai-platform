from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.observability import (
    AvailabilityWindow,
    HealthAcceptance,
    HealthDomain,
    HealthEvaluation,
    HealthEvidence,
    HealthFinding,
    HealthHistory,
    ObservabilityHeartbeat,
    ObservabilityProfile,
    ObservedComponent,
    ObservedDependency,
    ObservedSignal,
)
from app.repositories.observability import ObservabilityRepository
from app.schemas.observability import (
    AvailabilityWindowCreate,
    AvailabilityWindowRead,
    HealthAcceptanceRead,
    HealthDomainCreate,
    HealthDomainRead,
    HealthEvaluationRead,
    HealthEvaluationRequest,
    HealthEvidenceRead,
    HealthFindingRead,
    HealthHistoryRead,
    HeartbeatCreate,
    HeartbeatRead,
    ObservabilityGateResult,
    ObservabilityLatestResponse,
    ObservabilityProfileCreate,
    ObservabilityProfileRead,
    ObservabilityReadinessResponse,
    ObservedComponentCreate,
    ObservedComponentRead,
    ObservedDependencyCreate,
    ObservedDependencyRead,
    ObservedSignalCreate,
    ObservedSignalRead,
)
from app.services.readiness_contract import build_readiness_evidence

OBSERVABILITY_RUNTIME_VERSION = "observability-runtime.v1"
OBSERVABILITY_CONTRACT_VERSION = "observability.evidence.v1"
OBSERVABILITY_GATE_CODES = (
    "observability_evidence_available",
    "observability_health_verified",
    "observability_signal_coverage",
    "observability_component_readiness",
    "observability_freshness_valid",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _audit(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    resource_type: str,
    resource_id: uuid.UUID,
    action: str,
    actor_id: str | None,
    correlation_id: str | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    state = {
        **(after or {}),
        "action": action,
        "correlation_id": correlation_id,
        "postgresql_source_of_truth": True,
        "runtime_version": OBSERVABILITY_RUNTIME_VERSION,
    }
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_type="service",
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            summary=f"observability runtime: {action}",
            metadata_json=state,
        )
    )
    db.add(
        AuditHistory(
            organization_id=organization_id,
            entity_type=resource_type,
            entity_id=str(resource_id),
            action=action,
            before_state={},
            after_state=state,
            actor_type="service",
            actor_id=actor_id,
        )
    )


def _same(existing: Any, payload: dict[str, Any], fields: tuple[str, ...]) -> bool:
    persisted = {field: getattr(existing, field) for field in fields}
    expected = {field: payload.get(field) for field in fields}
    return stable_hash(persisted) == stable_hash(expected)


def create_observability_profile(db: Session, payload: ObservabilityProfileCreate) -> ObservabilityProfileRead:
    repo = ObservabilityRepository(db)
    fields = (
        "scope",
        "organization_id",
        "profile_code",
        "name",
        "description",
        "version",
        "status",
        "evidence_max_age_seconds",
        "heartbeat_max_age_seconds",
        "minimum_availability_percentage",
        "minimum_signal_coverage_percentage",
        "thresholds",
        "contract_version",
        "runtime_version",
    )
    data = payload.model_dump(exclude={"created_by"})
    existing = repo.find_profile(payload.scope, payload.organization_id, payload.profile_code, payload.version)
    if existing is not None:
        if not _same(existing, data, fields):
            raise ValueError("observability_profile_conflict")
        return ObservabilityProfileRead.model_validate(existing)
    if payload.status == "active":
        repo.deactivate_profiles(payload.scope, payload.organization_id)
    row = repo.add(
        ObservabilityProfile(
            **data,
            created_by=payload.created_by,
            activated_at=_now() if payload.status == "active" else None,
        )
    )
    _audit(
        db,
        organization_id=row.organization_id,
        resource_type="runtime.observability_profile",
        resource_id=row.id,
        action="created",
        actor_id=row.created_by,
        after={"profile_code": row.profile_code, "version": row.version, "status": row.status},
    )
    return ObservabilityProfileRead.model_validate(row)


def register_health_domain(db: Session, payload: HealthDomainCreate) -> HealthDomainRead:
    repo = ObservabilityRepository(db)
    profile = repo.get_profile(payload.profile_id, payload.scope, payload.organization_id)
    if profile is None:
        raise ValueError("observability_profile_not_found")
    data = payload.model_dump(exclude={"created_by"})
    existing = repo.find_domain(profile.id, payload.domain_code, payload.version)
    fields = tuple(data.keys())
    if existing is not None:
        if not _same(existing, data, fields):
            raise ValueError("health_domain_conflict")
        return HealthDomainRead.model_validate(existing)
    row = repo.add(HealthDomain(**data, created_by=payload.created_by))
    _audit(
        db,
        organization_id=row.organization_id,
        resource_type="runtime.observability_health_domain",
        resource_id=row.id,
        action="registered",
        actor_id=row.created_by,
        after={"domain_code": row.domain_code},
    )
    return HealthDomainRead.model_validate(row)


def register_observed_component(db: Session, payload: ObservedComponentCreate) -> ObservedComponentRead:
    repo = ObservabilityRepository(db)
    domain = repo.get_domain(payload.health_domain_id, payload.scope, payload.organization_id)
    if domain is None:
        raise ValueError("health_domain_not_found")
    data = payload.model_dump(exclude={"created_by"})
    existing = repo.find_component(domain.id, payload.component_code, payload.version)
    fields = tuple(data.keys())
    if existing is not None:
        if not _same(existing, data, fields):
            raise ValueError("observed_component_conflict")
        return ObservedComponentRead.model_validate(existing)
    row = repo.add(ObservedComponent(**data, created_by=payload.created_by))
    _audit(
        db,
        organization_id=row.organization_id,
        resource_type="runtime.observability_component",
        resource_id=row.id,
        action="registered",
        actor_id=row.created_by,
        after={"component_code": row.component_code},
    )
    return ObservedComponentRead.model_validate(row)


def register_observed_dependency(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
    payload: ObservedDependencyCreate,
    actor_id: str | None,
) -> ObservedDependencyRead:
    repo = ObservabilityRepository(db)
    component = repo.get_component(payload.component_id, scope, organization_id)
    if component is None:
        raise ValueError("observed_component_not_found")
    data = payload.model_dump()
    existing = repo.find_dependency(component.id, payload.dependency_code, payload.version)
    if existing is not None:
        if not _same(existing, data, tuple(data.keys())):
            raise ValueError("observed_dependency_conflict")
        return ObservedDependencyRead.model_validate(existing)
    row = repo.add(ObservedDependency(**data))
    _audit(
        db,
        organization_id=component.organization_id,
        resource_type="runtime.observability_dependency",
        resource_id=row.id,
        action="registered",
        actor_id=actor_id,
        after={"dependency_code": row.dependency_code, "status": row.status},
    )
    return ObservedDependencyRead.model_validate(row)


def register_observed_signal(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
    payload: ObservedSignalCreate,
    actor_id: str | None,
) -> ObservedSignalRead:
    repo = ObservabilityRepository(db)
    component = repo.get_component(payload.component_id, scope, organization_id)
    if component is None:
        raise ValueError("observed_component_not_found")
    data = payload.model_dump(mode="json")
    input_hash = stable_hash(data)
    existing = repo.find_signal(component.id, payload.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("observability_signal_idempotency_conflict")
        return ObservedSignalRead.model_validate(existing)
    row = repo.add(ObservedSignal(**payload.model_dump(), input_hash=input_hash))
    _audit(
        db,
        organization_id=component.organization_id,
        resource_type="runtime.observability_signal",
        resource_id=row.id,
        action="registered",
        actor_id=actor_id,
        after={"signal_code": row.signal_code, "status": row.status},
    )
    return ObservedSignalRead.model_validate(row)


def register_heartbeat(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
    payload: HeartbeatCreate,
    actor_id: str | None,
) -> HeartbeatRead:
    repo = ObservabilityRepository(db)
    component = repo.get_component(payload.component_id, scope, organization_id)
    if component is None:
        raise ValueError("observed_component_not_found")
    data = payload.model_dump(mode="json")
    input_hash = stable_hash(data)
    existing = repo.find_heartbeat(component.id, payload.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("observability_heartbeat_idempotency_conflict")
        return HeartbeatRead.model_validate(existing)
    row = repo.add(ObservabilityHeartbeat(**payload.model_dump(), input_hash=input_hash))
    _audit(
        db,
        organization_id=component.organization_id,
        resource_type="runtime.observability_heartbeat",
        resource_id=row.id,
        action="registered",
        actor_id=actor_id,
        after={"status": row.status, "observed_at": row.observed_at.isoformat()},
    )
    return HeartbeatRead.model_validate(row)


def register_availability_window(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
    payload: AvailabilityWindowCreate,
    actor_id: str | None,
) -> AvailabilityWindowRead:
    repo = ObservabilityRepository(db)
    component = repo.get_component(payload.component_id, scope, organization_id)
    if component is None:
        raise ValueError("observed_component_not_found")
    data = payload.model_dump(mode="json")
    input_hash = stable_hash(data)
    existing = repo.find_availability(component.id, payload.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("observability_availability_idempotency_conflict")
        return AvailabilityWindowRead.model_validate(existing)
    total = payload.available_seconds + payload.unavailable_seconds
    percentage = round((payload.available_seconds / total) * 100, 4) if total else 0.0
    row = repo.add(
        AvailabilityWindow(**payload.model_dump(), availability_percentage=percentage, input_hash=input_hash)
    )
    _audit(
        db,
        organization_id=component.organization_id,
        resource_type="runtime.observability_availability",
        resource_id=row.id,
        action="registered",
        actor_id=actor_id,
        after={"availability_percentage": percentage},
    )
    return AvailabilityWindowRead.model_validate(row)


def _latest_by(rows: list[Any], key) -> dict[Any, Any]:
    selected: dict[Any, Any] = {}
    for row in rows:
        selected.setdefault(key(row), row)
    return selected


def _finding(
    code: str,
    finding_type: str,
    severity: str,
    summary: str,
    *,
    component_id: uuid.UUID | None = None,
    dependency_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "finding_code": code,
        "finding_type": finding_type,
        "severity": severity,
        "status": "open",
        "summary": summary,
        "component_id": component_id,
        "dependency_id": dependency_id,
        "details": details or {},
    }


def evaluate_observability(db: Session, request: HealthEvaluationRequest) -> HealthEvaluationRead:
    repo = ObservabilityRepository(db)
    profile = repo.get_profile(request.profile_id, request.scope, request.organization_id)
    if profile is None or profile.status != "active":
        raise ValueError("active_observability_profile_not_found")
    domains = list(_latest_by(repo.list_domains(profile.id), lambda item: item.domain_code).values())
    components = list(
        _latest_by(
            repo.list_components(request.scope, request.organization_id, profile_id=profile.id),
            lambda item: (item.health_domain_id, item.component_code),
        ).values()
    )
    component_ids = [item.id for item in components]
    dependencies = repo.list_dependencies(component_ids)
    signals = repo.list_signals(component_ids)
    heartbeats = repo.list_heartbeats(component_ids)
    availability = repo.list_availability(component_ids)
    latest_signals = _latest_by(signals, lambda item: (item.component_id, item.signal_code))
    latest_heartbeats = _latest_by(heartbeats, lambda item: item.component_id)
    latest_availability = _latest_by(availability, lambda item: item.component_id)
    latest_dependencies = _latest_by(dependencies, lambda item: (item.component_id, item.dependency_code))
    evidence_ids = {
        "health_domain_ids": [str(item.id) for item in domains],
        "component_ids": [str(item.id) for item in components],
        "dependency_ids": [str(item.id) for item in latest_dependencies.values()],
        "signal_ids": [str(item.id) for item in latest_signals.values()],
        "heartbeat_ids": [str(item.id) for item in latest_heartbeats.values()],
        "availability_ids": [str(item.id) for item in latest_availability.values()],
    }
    input_payload = {
        "scope": request.scope,
        "organization_id": str(request.organization_id) if request.organization_id else None,
        "profile_id": str(profile.id),
        **evidence_ids,
    }
    input_hash = stable_hash(input_payload)
    existing = repo.find_evaluation(request.scope, request.organization_id, request.idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError("observability_evaluation_idempotency_conflict")
        return HealthEvaluationRead.model_validate(existing)

    now = _now()
    required_components = [item for item in components if item.required and item.status != "inactive"]
    findings: list[dict[str, Any]] = []
    observation_times: list[datetime] = []

    component_failed = not required_components
    if not required_components:
        findings.append(
            _finding("components_missing", "component", "critical", "No required observed components are registered.")
        )
    active_component_codes = {item.component_code for item in required_components}
    missing_declared_components = sorted(
        {
            code
            for domain in domains
            if domain.status == "active"
            for code in domain.required_component_codes
            if code not in active_component_codes
        }
    )
    if missing_declared_components:
        component_failed = True
        for code in missing_declared_components:
            findings.append(
                _finding(
                    f"component_{code}_missing",
                    "component",
                    "critical",
                    f"Required declared component {code} is not registered and active.",
                )
            )
    for component in required_components:
        if component.status in {"failed", "unknown"}:
            component_failed = True
            findings.append(
                _finding(
                    f"component_{component.component_code}_not_ready",
                    "component",
                    "critical",
                    f"Required component {component.component_code} is {component.status}.",
                    component_id=component.id,
                )
            )

    heartbeat_failed = False
    heartbeat_degraded = False
    for component in required_components:
        heartbeat = latest_heartbeats.get(component.id)
        stale = bool(
            heartbeat
            and (
                now - heartbeat.observed_at > timedelta(seconds=profile.heartbeat_max_age_seconds)
                or (heartbeat.expires_at is not None and heartbeat.expires_at <= now)
            )
        )
        if heartbeat is None or stale or heartbeat.status == "failed":
            heartbeat_failed = True
            findings.append(
                _finding(
                    f"heartbeat_{component.component_code}_invalid",
                    "heartbeat",
                    "critical",
                    f"Required component {component.component_code} has no fresh healthy heartbeat.",
                    component_id=component.id,
                )
            )
        elif heartbeat.status == "degraded":
            heartbeat_degraded = True
            findings.append(
                _finding(
                    f"heartbeat_{component.component_code}_degraded",
                    "heartbeat",
                    "warning",
                    f"Component {component.component_code} heartbeat is degraded.",
                    component_id=component.id,
                )
            )
        if heartbeat:
            observation_times.append(heartbeat.observed_at)

    expected_signals = [
        (component, code) for component in required_components for code in component.required_signal_codes
    ]
    covered_signals = 0
    signal_failed = False
    signal_degraded = False
    for component, signal_code in expected_signals:
        signal = latest_signals.get((component.id, signal_code))
        fresh = bool(
            signal
            and now - signal.observed_at <= timedelta(seconds=profile.evidence_max_age_seconds)
            and (signal.expires_at is None or signal.expires_at > now)
        )
        if fresh:
            covered_signals += 1
        if not fresh or (signal and signal.status in {"failed", "unknown"}):
            signal_failed = True
            findings.append(
                _finding(
                    f"signal_{component.component_code}_{signal_code}_invalid",
                    "signal",
                    "critical",
                    f"Required signal {signal_code} for {component.component_code} is missing, stale, or failed.",
                    component_id=component.id,
                )
            )
        elif signal and signal.status == "degraded":
            signal_degraded = True
            findings.append(
                _finding(
                    f"signal_{component.component_code}_{signal_code}_degraded",
                    "signal",
                    "warning",
                    f"Signal {signal_code} for {component.component_code} is degraded.",
                    component_id=component.id,
                )
            )
        if signal:
            observation_times.append(signal.observed_at)
    coverage = round((covered_signals / len(expected_signals)) * 100, 4) if expected_signals else 0.0
    coverage_failed = not expected_signals or coverage < float(profile.minimum_signal_coverage_percentage)
    if coverage_failed:
        findings.append(
            _finding(
                "signal_coverage_below_threshold",
                "coverage",
                "critical",
                "Persisted signal coverage is below the configured threshold.",
                details={"observed": coverage, "required": float(profile.minimum_signal_coverage_percentage)},
            )
        )

    dependency_failed = False
    dependency_degraded = False
    for dependency in latest_dependencies.values():
        expired = dependency.expires_at is not None and dependency.expires_at <= now
        if dependency.critical and (expired or dependency.status in {"failed", "unknown"}):
            dependency_failed = True
            findings.append(
                _finding(
                    f"dependency_{dependency.dependency_code}_invalid",
                    "dependency",
                    "critical",
                    f"Critical dependency {dependency.dependency_code} is unavailable or stale.",
                    component_id=dependency.component_id,
                    dependency_id=dependency.id,
                )
            )
        elif expired or dependency.status == "degraded":
            dependency_degraded = True
            findings.append(
                _finding(
                    f"dependency_{dependency.dependency_code}_degraded",
                    "dependency",
                    "warning",
                    f"Dependency {dependency.dependency_code} is degraded or stale.",
                    component_id=dependency.component_id,
                    dependency_id=dependency.id,
                )
            )
        observation_times.append(dependency.observed_at)

    percentages: list[float] = []
    availability_failed = False
    availability_degraded = False
    for component in required_components:
        window = latest_availability.get(component.id)
        if window is None:
            availability_failed = True
            findings.append(
                _finding(
                    f"availability_{component.component_code}_missing",
                    "availability",
                    "critical",
                    f"No persisted availability window exists for {component.component_code}.",
                    component_id=component.id,
                )
            )
            continue
        value = float(window.availability_percentage)
        percentages.append(value)
        observation_times.append(window.window_end)
        if value < float(profile.minimum_availability_percentage) or window.status == "failed":
            availability_failed = True
            findings.append(
                _finding(
                    f"availability_{component.component_code}_below_threshold",
                    "availability",
                    "critical",
                    f"Availability for {component.component_code} is below threshold.",
                    component_id=component.id,
                    details={"observed": value, "required": float(profile.minimum_availability_percentage)},
                )
            )
        elif window.status == "degraded":
            availability_degraded = True
    availability_percentage = round(sum(percentages) / len(percentages), 4) if percentages else 0.0

    evidence_age_seconds = max((max(0, int((now - item).total_seconds())) for item in observation_times), default=None)
    freshness_failed = evidence_age_seconds is None or evidence_age_seconds > profile.evidence_max_age_seconds
    if freshness_failed:
        findings.append(
            _finding(
                "observability_evidence_stale",
                "freshness",
                "critical",
                "Observability evidence is absent or older than the configured maximum age.",
                details={"evidence_age_seconds": evidence_age_seconds, "maximum": profile.evidence_max_age_seconds},
            )
        )

    def status(failed: bool, degraded: bool = False) -> str:
        return "failed" if failed else "degraded" if degraded else "healthy"

    availability_status = status(availability_failed, availability_degraded)
    heartbeat_status = status(heartbeat_failed, heartbeat_degraded)
    signal_status = status(signal_failed, signal_degraded)
    dependency_status = status(dependency_failed, dependency_degraded)
    coverage_status = status(coverage_failed)
    freshness_status = status(freshness_failed)
    component_status = status(component_failed)
    statuses = [
        availability_status,
        heartbeat_status,
        signal_status,
        dependency_status,
        coverage_status,
        freshness_status,
        component_status,
    ]
    overall_health = "failed" if "failed" in statuses else "degraded" if "degraded" in statuses else "healthy"
    blockers = [
        {"code": item["finding_code"], "message": item["summary"], "severity": item["severity"]}
        for item in findings
        if item["severity"] in {"error", "critical"}
    ]
    warnings = [
        {"code": item["finding_code"], "message": item["summary"], "severity": item["severity"]}
        for item in findings
        if item["severity"] == "warning"
    ]
    recommendations = [
        {
            "code": f"resolve_{item['finding_code']}",
            "summary": item["summary"],
            "priority": "critical" if item["severity"] == "critical" else "normal",
        }
        for item in findings
    ]
    next_actions = [
        {"action": item["code"], "source_finding": item["code"].removeprefix("resolve_")} for item in recommendations
    ]
    acceptance_status = "passed" if overall_health == "healthy" else "failed"
    result_payload = {
        **input_payload,
        "overall_health": overall_health,
        "availability_status": availability_status,
        "heartbeat_status": heartbeat_status,
        "signal_status": signal_status,
        "dependency_status": dependency_status,
        "coverage_status": coverage_status,
        "freshness_status": freshness_status,
        "component_status": component_status,
        "acceptance_status": acceptance_status,
        "availability_percentage": availability_percentage,
        "signal_coverage_percentage": coverage,
        "evidence_age_seconds": evidence_age_seconds,
        "blockers": blockers,
        "warnings": warnings,
    }
    evaluation = repo.add(
        HealthEvaluation(
            profile_id=profile.id,
            organization_id=request.organization_id,
            scope=request.scope,
            overall_health=overall_health,
            availability_status=availability_status,
            heartbeat_status=heartbeat_status,
            signal_status=signal_status,
            dependency_status=dependency_status,
            coverage_status=coverage_status,
            freshness_status=freshness_status,
            component_status=component_status,
            acceptance_status=acceptance_status,
            availability_percentage=availability_percentage,
            signal_coverage_percentage=coverage,
            evidence_age_seconds=evidence_age_seconds,
            blockers=blockers,
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions,
            idempotency_key=request.idempotency_key,
            input_hash=input_hash,
            result_hash=stable_hash(result_payload),
            correlation_id=request.correlation_id or f"observability:{uuid.uuid4()}",
            contract_version=profile.contract_version,
            runtime_version=profile.runtime_version,
            requested_by=request.requested_by,
            evaluated_at=now,
        )
    )
    finding_rows = [repo.add(HealthFinding(evaluation_id=evaluation.id, **item)) for item in findings]
    evidence_payload = {**result_payload, "finding_ids": [str(item.id) for item in finding_rows]}
    evidence = repo.add(
        HealthEvidence(
            evaluation_id=evaluation.id,
            origin="observability_evidence_runtime",
            source="runtime.observability_persisted_evidence",
            contract_version=profile.contract_version,
            runtime_version=profile.runtime_version,
            evaluation_timestamp=now,
            expires_at=now + timedelta(seconds=profile.evidence_max_age_seconds),
            component_ids=evidence_ids["component_ids"],
            dependency_ids=evidence_ids["dependency_ids"],
            heartbeat_ids=evidence_ids["heartbeat_ids"],
            signal_ids=evidence_ids["signal_ids"],
            finding_ids=[str(item.id) for item in finding_rows],
            evidence_payload=evidence_payload,
            evidence_hash=stable_hash(evidence_payload),
        )
    )
    gate_conditions = {
        "observability_evidence_available": True,
        "observability_health_verified": overall_health == "healthy",
        "observability_signal_coverage": coverage_status == "healthy",
        "observability_component_readiness": component_status == "healthy"
        and heartbeat_status == "healthy"
        and dependency_status == "healthy"
        and availability_status == "healthy",
        "observability_freshness_valid": freshness_status == "healthy",
    }
    gates = [
        ObservabilityGateResult(
            gate_code=code,
            status="passed" if passed else "failed",
            summary=f"{code.replace('_', ' ').capitalize()}: {'verified' if passed else 'not satisfied'}.",
            evidence_reference=str(evidence.id),
        ).model_dump(mode="json")
        for code, passed in gate_conditions.items()
    ]
    acceptance = repo.add(
        HealthAcceptance(
            evaluation_id=evaluation.id,
            organization_id=request.organization_id,
            scope=request.scope,
            status="passed" if all(gate_conditions.values()) else "failed",
            gate_results=gates,
            blocker_count=len(blockers),
            warning_count=len(warnings),
            evidence_age_seconds=evidence_age_seconds,
            result_hash=stable_hash(gates),
            accepted_by=request.requested_by,
            accepted_at=now,
        )
    )
    history = repo.add(
        HealthHistory(
            evaluation_id=evaluation.id,
            organization_id=request.organization_id,
            scope=request.scope,
            overall_health=overall_health,
            availability_percentage=availability_percentage,
            signal_coverage_percentage=coverage,
            evidence_age_seconds=evidence_age_seconds,
            component_summary={
                "total": len(components),
                "required": len(required_components),
                "status": component_status,
            },
            dependency_summary={"total": len(latest_dependencies), "status": dependency_status},
            finding_summary={"total": len(finding_rows), "blockers": len(blockers), "warnings": len(warnings)},
            captured_at=now,
        )
    )
    for finding in finding_rows:
        _audit(
            db,
            organization_id=request.organization_id,
            resource_type="runtime.observability_health_finding",
            resource_id=finding.id,
            action="generated",
            actor_id=request.requested_by,
            correlation_id=evaluation.correlation_id,
            after={
                "evaluation_id": str(evaluation.id),
                "finding_code": finding.finding_code,
                "severity": finding.severity,
            },
        )
    _audit(
        db,
        organization_id=request.organization_id,
        resource_type="runtime.observability_health_evidence",
        resource_id=evidence.id,
        action="generated",
        actor_id=request.requested_by,
        correlation_id=evaluation.correlation_id,
        after={
            "evaluation_id": str(evaluation.id),
            "evidence_hash": evidence.evidence_hash,
            "expires_at": evidence.expires_at.isoformat(),
        },
    )
    _audit(
        db,
        organization_id=request.organization_id,
        resource_type="runtime.observability_health_acceptance",
        resource_id=acceptance.id,
        action="evaluated",
        actor_id=request.requested_by,
        correlation_id=evaluation.correlation_id,
        after={"evaluation_id": str(evaluation.id), "status": acceptance.status},
    )
    _audit(
        db,
        organization_id=request.organization_id,
        resource_type="runtime.observability_health_history",
        resource_id=history.id,
        action="captured",
        actor_id=request.requested_by,
        correlation_id=evaluation.correlation_id,
        after={"evaluation_id": str(evaluation.id), "overall_health": history.overall_health},
    )
    _audit(
        db,
        organization_id=request.organization_id,
        resource_type="runtime.observability_health_evaluation",
        resource_id=evaluation.id,
        action="evaluated",
        actor_id=request.requested_by,
        correlation_id=evaluation.correlation_id,
        after={"overall_health": overall_health, "acceptance_id": str(acceptance.id), "evidence_id": str(evidence.id)},
    )
    return HealthEvaluationRead.model_validate(evaluation)


def build_observability_readiness(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> ObservabilityReadinessResponse:
    repo = ObservabilityRepository(db)
    profile = repo.active_profile(scope, organization_id)
    evaluation = repo.latest_evaluation(scope, organization_id, profile_id=profile.id) if profile else None
    acceptance = repo.acceptance(evaluation.id) if evaluation else None
    evidence = repo.evidence(evaluation.id) if evaluation else []
    components = (
        list(
            _latest_by(
                repo.list_components(scope, organization_id, profile_id=profile.id),
                lambda item: (item.health_domain_id, item.component_code),
            ).values()
        )
        if profile
        else []
    )
    component_ids = [item.id for item in components]
    dependencies = repo.list_dependencies(component_ids)
    latest_dependencies = list(
        _latest_by(dependencies, lambda item: (item.component_id, item.dependency_code)).values()
    )
    heartbeats = repo.list_heartbeats(component_ids)
    latest_heartbeats = list(_latest_by(heartbeats, lambda item: item.component_id).values())
    findings = repo.findings(evaluation.id) if evaluation else []
    now = _now()
    expired = bool(evidence and evidence[0].expires_at <= now)
    gates = [ObservabilityGateResult.model_validate(item) for item in (acceptance.gate_results if acceptance else [])]
    if not gates:
        gates = [
            ObservabilityGateResult(
                gate_code=gate_code,
                status="not_evaluated",
                summary="Persisted Observability evidence is not available.",
                evidence_reference=None,
            )
            for gate_code in (
                "observability_evidence_available",
                "observability_health_verified",
                "observability_signal_coverage",
                "observability_component_readiness",
                "observability_freshness_valid",
            )
        ]
    if expired:
        gates = [
            gate.model_copy(
                update={
                    "status": "blocked" if gate.gate_code == "observability_freshness_valid" else gate.status,
                    "summary": "Persisted observability evidence is expired."
                    if gate.gate_code == "observability_freshness_valid"
                    else gate.summary,
                }
            )
            for gate in gates
        ]
    status = "not_evaluated"
    if evaluation and acceptance:
        status = "blocked" if expired else evaluation.overall_health
    evidence_age = (
        max(0, int((now - evaluation.evaluated_at).total_seconds())) + int(evaluation.evidence_age_seconds or 0)
        if evaluation
        else None
    )
    blockers = list(evaluation.blockers) if evaluation else []
    if expired:
        blockers.append(
            {
                "code": "observability_evidence_expired",
                "message": "Persisted observability evidence is expired.",
                "severity": "critical",
            }
        )
    contract_status = (
        "expired"
        if expired
        else "passed"
        if status == "healthy"
        else "failed"
        if status == "failed"
        else "blocked"
        if status in {"blocked", "degraded"}
        else "not_evaluated"
    )
    warnings = list(evaluation.warnings) if evaluation else []
    recommendations = list(evaluation.recommendations) if evaluation else []
    next_actions = list(evaluation.next_actions) if evaluation else [{"action": "create_observability_profile"}]
    integrity_errors = [
        {
            "code": "observability_evidence_corrupt",
            "message": "Persisted observability evidence hash does not match its payload.",
            "evidence_id": str(item.id),
        }
        for item in evidence
        if stable_hash(item.evidence_payload) != item.evidence_hash
    ]
    evidence_contract = build_readiness_evidence(
        domain="observability",
        status=contract_status,
        gate_results=gates,
        blockers=blockers,
        warnings=warnings,
        recommendations=recommendations,
        next_actions=next_actions,
        runtime_version=evaluation.runtime_version if evaluation else OBSERVABILITY_RUNTIME_VERSION,
        evaluation_timestamp=evaluation.evaluated_at if evaluation else None,
        expires_at=min((item.expires_at for item in evidence), default=None),
        evidence_origin=evidence[0].origin if evidence else "observability_runtime",
        evaluation_duration=0,
        components_evaluated=[item.component_code for item in components],
        evidence_ids=[str(item.id) for item in evidence],
        source_contract_version=evaluation.contract_version if evaluation else None,
        supported_contract_versions=(OBSERVABILITY_CONTRACT_VERSION,) if evaluation else (),
        source_runtime_version=evaluation.runtime_version if evaluation else None,
        supported_runtime_versions=(OBSERVABILITY_RUNTIME_VERSION,) if evaluation else (),
        integrity_errors=integrity_errors,
    )
    return ObservabilityReadinessResponse(
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        scope=scope,
        organization_id=organization_id,
        active_profile=ObservabilityProfileRead.model_validate(profile) if profile else None,
        latest_evaluation=HealthEvaluationRead.model_validate(evaluation) if evaluation else None,
        latest_acceptance=HealthAcceptanceRead.model_validate(acceptance) if acceptance else None,
        overall_health=evaluation.overall_health if evaluation else "not_evaluated",
        availability_status=evaluation.availability_status if evaluation else "not_evaluated",
        heartbeat_status=evaluation.heartbeat_status if evaluation else "not_evaluated",
        signal_status=evaluation.signal_status if evaluation else "not_evaluated",
        dependency_status=evaluation.dependency_status if evaluation else "not_evaluated",
        coverage_status=evaluation.coverage_status if evaluation else "not_evaluated",
        freshness_status="failed" if expired else evaluation.freshness_status if evaluation else "not_evaluated",
        component_status=evaluation.component_status if evaluation else "not_evaluated",
        acceptance_status="blocked" if expired else acceptance.status if acceptance else "not_evaluated",
        availability_percentage=float(evaluation.availability_percentage) if evaluation else None,
        signal_coverage_percentage=float(evaluation.signal_coverage_percentage) if evaluation else None,
        components=[ObservedComponentRead.model_validate(item) for item in components],
        dependencies=[ObservedDependencyRead.model_validate(item) for item in latest_dependencies],
        heartbeats=[HeartbeatRead.model_validate(item) for item in latest_heartbeats],
        findings=[HealthFindingRead.model_validate(item) for item in findings],
        blockers=blockers,
        warnings=warnings,
        recommendations=recommendations,
        next_actions=next_actions,
        evidence_age_seconds=evidence_age,
        gate_results=gates,
        evaluated_at=evaluation.evaluated_at if evaluation else None,
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
        evidence_contract=evidence_contract,
    )


def latest_observability_result(
    db: Session, *, scope: str, organization_id: uuid.UUID | None
) -> ObservabilityLatestResponse:
    repo = ObservabilityRepository(db)
    profile = repo.active_profile(scope, organization_id)
    evaluation = repo.latest_evaluation(scope, organization_id, profile_id=profile.id) if profile else None
    if evaluation is None:
        return ObservabilityLatestResponse(found=False)
    return ObservabilityLatestResponse(
        found=True,
        evaluation=HealthEvaluationRead.model_validate(evaluation),
        acceptance=HealthAcceptanceRead.model_validate(repo.acceptance(evaluation.id)),
        evidence=[HealthEvidenceRead.model_validate(item) for item in repo.evidence(evaluation.id)],
    )


def observability_history(
    db: Session, *, scope: str, organization_id: uuid.UUID | None, limit: int = 200
) -> list[HealthHistoryRead]:
    return [
        HealthHistoryRead.model_validate(item)
        for item in ObservabilityRepository(db).history(scope, organization_id, limit)
    ]
