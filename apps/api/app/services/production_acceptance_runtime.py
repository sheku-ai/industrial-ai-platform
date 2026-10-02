from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.product_acceptance import AcceptanceExecution
from app.models.production_acceptance import (
    ProductionAcceptanceEvidence as ProductionAcceptanceEvidenceModel,
)
from app.models.production_acceptance import (
    ProductionAcceptanceGateResult as ProductionAcceptanceGateResultModel,
)
from app.models.production_acceptance import (
    ProductionAcceptanceRun,
)
from app.repositories.production_acceptance import ProductionAcceptanceRepository
from app.repositories.release_operational_evidence import ReleaseOperationalEvidenceRepository
from app.schemas.production_acceptance import (
    ConfigurationPreflightResult,
    ProductionAcceptanceDomainSummary,
    ProductionAcceptanceEvidence,
    ProductionAcceptanceGateResult,
    ProductionAcceptanceLatestResponse,
    ProductionAcceptanceRequest,
    ProductionAcceptanceRunResult,
    ProductionBlocker,
    ProductionWarning,
    ProductionWorkspaceRuntimeResponse,
)
from app.schemas.readiness import AuthoritativeReadinessEvidence
from app.schemas.release_operational_evidence import OperationalEvidenceRequest
from app.services.capacity_runtime import build_capacity_readiness
from app.services.database_revision import resolve_database_revision
from app.services.observability_runtime import build_observability_readiness
from app.services.portal_acceptance_runtime import build_portal_acceptance_readiness
from app.services.product_state_contract import build_product_state_contract
from app.services.production_acceptance_catalog import (
    CONTRACT_VERSION,
    PRODUCTION_ACCEPTANCE_GATES,
    ProductionGateDefinition,
)
from app.services.readiness_contract import READINESS_CONTRACT_VERSION, build_readiness_evidence
from app.services.recovery_objectives_runtime import build_recovery_readiness
from app.services.release_governance_runtime import get_latest_release_readiness
from app.services.release_operational_evidence_runtime import (
    build_operational_execution_key,
    configuration_preflight_from_evidence,
    refresh_configuration_preflight,
)
from app.services.security_acceptance_runtime import build_security_readiness

TERMINAL_RUN_STATUSES = {"passed", "failed", "blocked"}
DOMAIN_ORDER = ("functional", "operational", "security", "recovery", "deployment", "capacity", "portal")
NEXT_ACTIONS_BY_BLOCKER = {
    "BACKUP_POLICY_NOT_CONFIGURED": "configure_backup_policy",
    "LATEST_BACKUP_EVIDENCE_MISSING": "record_backup_evidence",
    "LATEST_RESTORE_VERIFICATION_MISSING": "verify_restore",
    "RPO_NOT_CONFIGURED": "configure_rpo",
    "RTO_NOT_CONFIGURED": "configure_rto",
    "OBJECT_STORAGE_RECOVERY_NOT_DEFINED": "define_object_storage_recovery",
    "DATABASE_RECOVERY_NOT_DEFINED": "define_database_recovery",
    "RECOVERY_EVIDENCE_NOT_FRESH": "refresh_recovery_evidence",
    "CAPACITY_PROFILE_NOT_DEFINED": "define_capacity_profile",
    "LOAD_TEST_NOT_COMPLETED": "complete_capacity_load_test",
    "CAPACITY_NOT_VALIDATED": "validate_capacity",
    "CAPACITY_BOTTLENECKS_NOT_RESOLVED": "resolve_capacity_bottlenecks",
    "PRODUCTION_CAPACITY_NOT_READY": "complete_capacity_acceptance",
    "ROLLBACK_TARGET_NOT_AVAILABLE": "validate_rollback_target",
    "DEPLOYMENT_MANIFEST_NOT_AVAILABLE": "publish_deployment_manifest",
}
SUPPORTED_DOMAIN_RUNTIME_VERSIONS = {
    "local_product_acceptance": "local-product-acceptance-runtime.v1",
    "observability": "observability-runtime.v1",
    "security": "security-acceptance-runtime.v1",
    "recovery": "recovery-evidence-runtime.v1",
    "release_governance": "release-governance-runtime.v1",
    "capacity": "capacity-load-evidence-runtime.v1",
    "portal": "portal-acceptance-runtime.v1",
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


def _latest_local_product_acceptance(db: Session, organization_id: uuid.UUID | None) -> AcceptanceExecution | None:
    statement = (
        select(AcceptanceExecution)
        .where(AcceptanceExecution.scenario == "local_product_acceptance")
        .order_by(AcceptanceExecution.completed_at.desc().nullslast(), AcceptanceExecution.created_at.desc())
    )
    if organization_id is not None:
        statement = statement.where(AcceptanceExecution.organization_id == organization_id)
    return db.scalar(statement.limit(1))


def _persist_evidence(
    db: Session,
    run: ProductionAcceptanceRun,
    evidence_payloads: dict[str, dict[str, Any]],
) -> dict[str, ProductionAcceptanceEvidenceModel]:
    repository = ProductionAcceptanceRepository(db)
    repository.clear_evidence(run.id)
    db.flush()
    evidence_by_type: dict[str, ProductionAcceptanceEvidenceModel] = {}
    observed_at = _utcnow()
    for evidence_type, payload in sorted(evidence_payloads.items()):
        evidence_hash = stable_hash(
            {
                "run_id": str(run.id),
                "evidence_type": evidence_type,
                "payload": payload,
            }
        )
        row = ProductionAcceptanceEvidenceModel(
            run_id=run.id,
            evidence_type=evidence_type,
            source_runtime=str(payload.get("evidence_origin") or payload.get("source") or evidence_type),
            source_entity_type=evidence_type,
            source_entity_id=(str((payload.get("evidence_ids") or [None])[0]) if payload.get("evidence_ids") else None),
            evidence_payload=_safe_json(payload),
            evidence_hash=evidence_hash,
            observed_at=observed_at,
        )
        db.add(row)
        evidence_by_type[evidence_type] = row
    db.flush()
    return evidence_by_type


def _collect_authoritative_evidence_payloads(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    configuration_preflight: ConfigurationPreflightResult,
    configuration_preflight_evidence_id: uuid.UUID,
) -> dict[str, dict[str, Any]]:
    scope = "organization" if organization_id else "platform"
    local_acceptance = _latest_local_product_acceptance(db, organization_id)
    local_report = local_acceptance.report if local_acceptance is not None else {}
    functional_passed = _mandatory_acceptance_gates_passed(local_report)
    functional_status = "passed" if functional_passed else "blocked" if local_acceptance else "not_evaluated"
    functional_gate = {
        "gate_code": "local_product_acceptance_passed",
        "status": functional_status,
        "summary": "Local Product Acceptance has persisted passing evidence."
        if functional_passed
        else "Local Product Acceptance does not have persisted passing evidence.",
        "evidence_reference": str(local_acceptance.id) if local_acceptance else None,
    }
    functional_contract = build_readiness_evidence(
        domain="local_product_acceptance",
        status=functional_status,
        gate_results=[functional_gate],
        blockers=[]
        if functional_passed
        else [{"code": "LOCAL_PRODUCT_ACCEPTANCE_NOT_PASSED", "message": functional_gate["summary"]}],
        warnings=[],
        runtime_version="local-product-acceptance-runtime.v1",
        evaluation_timestamp=(local_acceptance.completed_at or local_acceptance.created_at)
        if local_acceptance
        else None,
        expires_at=None,
        evidence_origin="local_product_acceptance_runtime",
        components_evaluated=["local_product_acceptance"],
        evidence_ids=[str(local_acceptance.id)] if local_acceptance else [],
    )
    observability = build_observability_readiness(db, scope=scope, organization_id=organization_id)
    security = build_security_readiness(db, scope=scope, organization_id=organization_id, refresh=False)
    recovery = build_recovery_readiness(db, scope=scope, organization_id=organization_id)
    capacity = build_capacity_readiness(db, scope=scope, organization_id=organization_id)
    portal = build_portal_acceptance_readiness(db, scope=scope, organization_id=organization_id)
    latest_release = get_latest_release_readiness(db)
    if latest_release.readiness is not None:
        deployment_contract = latest_release.readiness.evidence_contract
    else:
        deployment_contract = build_readiness_evidence(
            domain="release_governance",
            status="not_evaluated",
            gate_results=[],
            blockers=[
                {"code": "RELEASE_NOT_EVALUATED", "message": "Release Governance has no persisted release evidence."}
            ],
            warnings=[],
            runtime_version="release-governance-runtime.v1",
            evaluation_timestamp=None,
            expires_at=None,
            evidence_origin="release_governance_runtime",
        )
    configuration_payload = configuration_preflight.model_dump(mode="json")
    configuration_payload.update(
        {
            "evidence_ids": [str(configuration_preflight_evidence_id)],
            "evidence_origin": "release_operational_evidence_runtime",
        }
    )
    return {
        "functional_evidence_contract": functional_contract.model_dump(mode="json"),
        "operational_evidence_contract": observability.evidence_contract.model_dump(mode="json"),
        "security_evidence_contract": security.evidence_contract.model_dump(mode="json"),
        "recovery_evidence_contract": recovery.evidence_contract.model_dump(mode="json"),
        "deployment_evidence_contract": deployment_contract.model_dump(mode="json"),
        "capacity_evidence_contract": capacity.evidence_contract.model_dump(mode="json"),
        "portal_evidence_contract": portal.evidence_contract.model_dump(mode="json"),
        "configuration_preflight": configuration_payload,
    }


def _mandatory_acceptance_gates_passed(evidence: dict[str, Any]) -> bool:
    """Evaluate persisted Local Product Acceptance mandatory-gate evidence."""
    if evidence.get("release_candidate_eligible") is not True:
        return False
    if evidence.get("passed") is False:
        return False
    if "mandatory_gates_total" in evidence:
        mandatory_total = evidence["mandatory_gates_total"]
    elif "mandatory_gates" in evidence:
        mandatory_total = evidence["mandatory_gates"]
    else:
        return False
    mandatory_passed = evidence.get("mandatory_gates_passed", 0)
    if not isinstance(mandatory_total, int) or isinstance(mandatory_total, bool) or mandatory_total < 0:
        return False
    if not isinstance(mandatory_passed, int) or isinstance(mandatory_passed, bool) or mandatory_passed < 0:
        return False
    return mandatory_total == 0 or mandatory_passed == mandatory_total


def _evaluate_gate(
    gate: ProductionGateDefinition,
    evidence: dict[str, dict[str, Any]],
    preflight: ConfigurationPreflightResult,
) -> tuple[str, str, dict[str, Any]]:
    del preflight
    contract = evidence.get(f"{gate.domain}_evidence_contract", {})
    contract_gate = next(
        (item for item in contract.get("gate_results", []) if item.get("gate_code") == gate.gate_code),
        None,
    )
    if contract_gate is None:
        return (
            "not_evaluated",
            "The authoritative evidence contract did not provide this mandatory gate.",
            {"strategy": "authoritative_evidence_contract", "domain_evidence": contract},
        )
    return (
        str(contract_gate.get("status") or "not_evaluated"),
        str(contract_gate.get("summary") or gate.description),
        {
            "strategy": "authoritative_evidence_contract",
            "domain_evidence": contract,
            "gate_evidence": contract_gate,
        },
    )


def _domain_summary(
    domain: str,
    gates: list[ProductionAcceptanceGateResultModel],
) -> ProductionAcceptanceDomainSummary:
    def gate_value(gate: Any, attribute: str, default: Any = None) -> Any:
        return getattr(gate, attribute, default)

    def gate_identity(gate: Any) -> str:
        for attribute in ("gate_code", "gate_key", "key", "id"):
            value = gate_value(gate, attribute)
            if value is not None and str(value).strip():
                return str(value)
        return "unknown_gate"

    def gate_status(gate: Any) -> str:
        return str(gate_value(gate, "status", "not_evaluated") or "not_evaluated")

    def gate_summary(gate: Any) -> str:
        summary = gate_value(gate, "summary")
        return str(summary) if summary else f"{gate_identity(gate)} {gate_status(gate)}"

    def duration_ms(gate: Any) -> int:
        value = gate_value(gate, "duration_ms")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return 0
        if isinstance(value, float) and not value.is_integer():
            return 0
        return int(value)

    mandatory_gates = [gate for gate in gates if gate_value(gate, "mandatory", True) is not False]
    blockers = [
        ProductionBlocker(
            code=str(gate_value(gate, "blocker_code") or f"{gate_identity(gate)}_blocked"),
            gate_code=gate_identity(gate),
            domain=domain,
            message=gate_summary(gate),
        )
        for gate in mandatory_gates
        if gate_status(gate) in {"failed", "blocked"}
    ]
    warnings = [
        ProductionWarning(
            code=str(gate_value(gate, "warning_code") or f"{gate_identity(gate)}_warning"),
            gate_code=gate_identity(gate),
            domain=domain,
            message=gate_summary(gate),
        )
        for gate in gates
        if gate_status(gate) == "not_evaluated"
    ]
    if any(gate_status(gate) == "failed" for gate in mandatory_gates):
        status = "failed"
    elif any(gate_status(gate) == "blocked" for gate in mandatory_gates):
        status = "blocked"
    elif any(gate_status(gate) == "not_evaluated" for gate in mandatory_gates):
        status = "not_evaluated"
    elif mandatory_gates and all(gate_status(gate) == "passed" for gate in mandatory_gates):
        status = "passed"
    else:
        status = "blocked"
    evidence_ages: list[int] = []
    components_evaluated: set[str] = set()
    evidence_origins: set[str] = set()
    evidence_references: set[str] = set()
    evaluation_timestamps: list[datetime] = []
    for gate in gates:
        components = gate_value(gate, "components_evaluated")
        if isinstance(components, Iterable) and not isinstance(components, (str, bytes, Mapping)):
            components_evaluated.update(
                component for component in components if isinstance(component, str) and component
            )
        evidence_origin = gate_value(gate, "evidence_origin")
        if isinstance(evidence_origin, str) and evidence_origin:
            evidence_origins.add(evidence_origin)
        evidence_reference = gate_value(gate, "evidence_reference")
        if isinstance(evidence_reference, str) and evidence_reference:
            evidence_references.add(evidence_reference)
        evaluated_at = gate_value(gate, "evaluated_at")
        if isinstance(evaluated_at, datetime):
            evaluation_timestamps.append(evaluated_at)
        payload = gate_value(gate, "evidence_payload")
        if not isinstance(payload, Mapping):
            continue
        domain_evidence = payload.get("domain_evidence")
        if not isinstance(domain_evidence, Mapping):
            continue
        evidence_age = domain_evidence.get("evidence_age_seconds")
        if isinstance(evidence_age, int) and not isinstance(evidence_age, bool) and evidence_age >= 0:
            evidence_ages.append(evidence_age)
    return ProductionAcceptanceDomainSummary(
        domain=domain,
        status=status,
        mandatory_total=len(mandatory_gates),
        passed=len([gate for gate in gates if gate_status(gate) == "passed"]),
        failed=len([gate for gate in gates if gate_status(gate) == "failed"]),
        blocked=len([gate for gate in gates if gate_status(gate) == "blocked"]),
        not_evaluated=len([gate for gate in gates if gate_status(gate) == "not_evaluated"]),
        blockers=blockers,
        warnings=warnings,
        duration_ms=sum(duration_ms(gate) for gate in gates),
        components_evaluated=sorted(components_evaluated),
        evidence_origins=sorted(evidence_origins),
        evidence_references=sorted(evidence_references),
        evaluated_at=max(evaluation_timestamps, default=None),
        evidence_age_seconds=max(evidence_ages) if evidence_ages else None,
    )


def calculate_domain_summaries(
    gates: list[ProductionAcceptanceGateResultModel],
) -> dict[str, ProductionAcceptanceDomainSummary]:
    grouped: dict[str, list[ProductionAcceptanceGateResultModel]] = defaultdict(list)
    for gate in gates:
        grouped[gate.domain].append(gate)
    return {domain: _domain_summary(domain, grouped.get(domain, [])) for domain in DOMAIN_ORDER}


def production_ready_from_gates(
    run_status: str,
    gates: list[ProductionAcceptanceGateResultModel],
    result_hash: str | None,
) -> bool:
    mandatory = [gate for gate in gates if gate.mandatory]
    if run_status not in TERMINAL_RUN_STATUSES or not result_hash or not mandatory:
        return False
    return all(gate.status == "passed" for gate in mandatory)


def production_ready_from_evidence(
    gates: list[ProductionAcceptanceGateResultModel],
    preflight: ConfigurationPreflightResult,
) -> bool:
    mandatory = [gate for gate in gates if gate.mandatory]
    return bool(
        mandatory
        and all(gate.status == "passed" for gate in mandatory)
        and preflight.status == "passed"
        and not preflight.blockers
    )


def _gate_counts(gates: list[ProductionAcceptanceGateResultModel]) -> dict[str, int]:
    mandatory = [gate for gate in gates if gate.mandatory]
    return {
        "mandatory_total": len(mandatory),
        "passed": len([gate for gate in mandatory if gate.status == "passed"]),
        "failed": len([gate for gate in mandatory if gate.status == "failed"]),
        "blocked": len([gate for gate in mandatory if gate.status == "blocked"]),
        "not_evaluated": len([gate for gate in mandatory if gate.status == "not_evaluated"]),
    }


def _build_result_hash_payload(
    run: ProductionAcceptanceRun, gates: list[ProductionAcceptanceGateResultModel]
) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "scope": run.scope,
        "organization_id": str(run.organization_id) if run.organization_id else None,
        "contract_version": run.contract_version,
        "gates": [
            {
                "gate_code": gate.gate_code,
                "domain": gate.domain,
                "status": gate.status,
                "mandatory": gate.mandatory,
                "blocker_code": gate.blocker_code,
            }
            for gate in sorted(gates, key=lambda item: (item.domain, item.gate_code))
        ],
    }


def _normalize_request(request: ProductionAcceptanceRequest) -> tuple[str, uuid.UUID | None]:
    scope = request.scope
    organization_id = request.organization_id
    if scope == "platform":
        organization_id = None
    if scope == "organization" and organization_id is None:
        raise ValueError("organization_id_required")
    return scope, organization_id


def _input_hash(
    scope: str,
    organization_id: uuid.UUID | None,
    requested_by: str | None,
    configuration_preflight_evidence_id: uuid.UUID,
) -> str:
    return stable_hash(
        {
            "scope": scope,
            "organization_id": str(organization_id) if organization_id else None,
            "requested_by": requested_by,
            "configuration_preflight_evidence_id": configuration_preflight_evidence_id,
            "contract_version": CONTRACT_VERSION,
        }
    )


def _find_existing_run(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    input_hash: str,
    idempotency_key: str,
) -> ProductionAcceptanceRun | None:
    return ProductionAcceptanceRepository(db).find_idempotent_run(
        scope=scope,
        organization_id=organization_id,
        contract_version=CONTRACT_VERSION,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
    )


def _has_idempotency_conflict(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    input_hash: str,
    idempotency_key: str,
) -> bool:
    return ProductionAcceptanceRepository(db).has_idempotency_conflict(
        scope=scope,
        organization_id=organization_id,
        contract_version=CONTRACT_VERSION,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
    )


def _persist_gate_results(
    db: Session,
    run: ProductionAcceptanceRun,
    evidence_payloads: dict[str, dict[str, Any]],
    evidence_rows: dict[str, ProductionAcceptanceEvidenceModel],
    preflight: ConfigurationPreflightResult,
) -> list[ProductionAcceptanceGateResultModel]:
    repository = ProductionAcceptanceRepository(db)
    repository.clear_gate_results(run.id)
    db.flush()
    gate_rows: list[ProductionAcceptanceGateResultModel] = []
    evaluated_at = _utcnow()
    for gate in PRODUCTION_ACCEPTANCE_GATES:
        gate_started = perf_counter()
        status, summary, payload = _evaluate_gate(gate, evidence_payloads, preflight)
        primary_evidence_type = gate.evidence_requirements[0] if gate.evidence_requirements else None
        primary_evidence = evidence_rows.get(primary_evidence_type or "")
        contract_gate = payload.get("gate_evidence")
        domain_contract = payload.get("domain_evidence")
        row = ProductionAcceptanceGateResultModel(
            run_id=run.id,
            gate_code=gate.gate_code,
            domain=gate.domain,
            status=status,
            mandatory=gate.mandatory,
            summary=summary,
            blocker_code=gate.blocker_code if status in {"failed", "blocked"} else None,
            warning_code=gate.warning_code if status == "not_evaluated" else None,
            evidence_type=primary_evidence_type,
            evidence_reference=(
                str((contract_gate.get("evidence_ids") or [None])[0])
                if contract_gate and contract_gate.get("evidence_ids")
                else str(primary_evidence.id)
                if primary_evidence is not None
                else None
            ),
            evidence_payload=_safe_json(payload),
            duration_ms=max(0, int((perf_counter() - gate_started) * 1000)),
            components_evaluated=(
                list(domain_contract.get("components_evaluated") or [])
                if domain_contract
                else list(gate.evidence_requirements)
            ),
            evidence_origin=(
                str(domain_contract.get("evidence_origin"))
                if domain_contract and domain_contract.get("evidence_origin")
                else primary_evidence.source_runtime
                if primary_evidence is not None
                else "configuration"
            ),
            evaluated_at=evaluated_at,
        )
        db.add(row)
        gate_rows.append(row)
    db.flush()
    return gate_rows


def _run_result(
    run: ProductionAcceptanceRun,
    gates: list[ProductionAcceptanceGateResultModel],
    evidence: list[ProductionAcceptanceEvidenceModel],
    *,
    preflight: ConfigurationPreflightResult | None = None,
    reused: bool = False,
) -> ProductionAcceptanceRunResult:
    summaries = calculate_domain_summaries(gates)
    blockers = [blocker for summary in summaries.values() for blocker in summary.blockers]
    warnings = [warning for summary in summaries.values() for warning in summary.warnings]
    if preflight is not None:
        blockers.extend(preflight.blockers)
        warnings.extend(preflight.warnings)
    evaluated_at = run.completed_at or run.updated_at or run.started_at or run.requested_at
    evidence_contracts = _validated_evidence_contracts(run, evidence, evaluated_at)
    for contract in evidence_contracts:
        blockers.extend(
            ProductionBlocker(
                code=str(item.get("code") or "READINESS_CONTRACT_BLOCKED"),
                domain=contract.domain,
                message=str(
                    item.get("message") or item.get("reason") or "Authoritative readiness evidence is blocked."
                ),
            )
            for item in contract.blockers
        )
        warnings.extend(
            ProductionWarning(
                code=str(item.get("code") or "READINESS_CONTRACT_WARNING"),
                domain=contract.domain,
                message=str(
                    item.get("message") or item.get("reason") or "Authoritative readiness evidence reported a warning."
                ),
            )
            for item in contract.warnings
        )
    contracts_valid = len(evidence_contracts) == len(SUPPORTED_DOMAIN_RUNTIME_VERSIONS) and all(
        item.status == "passed" for item in evidence_contracts
    )
    contract_domains = [item.domain for item in evidence_contracts]
    contract_inventory_invalid = len(contract_domains) != len(SUPPORTED_DOMAIN_RUNTIME_VERSIONS) or set(
        contract_domains
    ) != set(SUPPORTED_DOMAIN_RUNTIME_VERSIONS)
    if contract_inventory_invalid:
        blockers.append(
            ProductionBlocker(
                code="READINESS_CONTRACT_INVENTORY_INVALID",
                domain="production_acceptance",
                message="Production Acceptance requires exactly one authoritative contract for every governed domain.",
            )
        )
    production_ready = bool(
        run.production_ready
        and preflight
        and preflight.status == "passed"
        and contracts_valid
        and run.contract_version == CONTRACT_VERSION
    )
    interrupted = run.status in {"pending", "running"} and run.completed_at is None
    incompatible_contract = run.contract_version != CONTRACT_VERSION
    contract_hardening_failed = contract_inventory_invalid or any(
        item.reason == "contract_hardening_failed" for item in evidence_contracts
    )
    evidence_expired = any(item.status == "expired" for item in evidence_contracts)
    evidence_stale = any(item.status == "stale" for item in evidence_contracts)
    response_status = (
        "interrupted"
        if interrupted
        else "failed"
        if incompatible_contract or contract_hardening_failed or (run.status == "passed" and not production_ready)
        else "expired"
        if evidence_expired
        else "stale"
        if evidence_stale
        else run.status
    )
    if interrupted:
        blockers.append(
            ProductionBlocker(
                code="PRODUCTION_ACCEPTANCE_INTERRUPTED",
                domain="production_acceptance",
                message="Production Acceptance execution was interrupted before completion.",
            )
        )
    if incompatible_contract:
        blockers.append(
            ProductionBlocker(
                code="UNSUPPORTED_PRODUCTION_ACCEPTANCE_CONTRACT",
                domain="production_acceptance",
                message="Production Acceptance contract version is unsupported.",
            )
        )
    blockers = list({(item.code, item.gate_code, item.domain, item.message): item for item in blockers}.values())
    warnings = list({(item.code, item.gate_code, item.domain, item.message): item for item in warnings}.values())
    return ProductionAcceptanceRunResult(
        run_id=run.id,
        correlation_id=run.correlation_id,
        scope=run.scope,
        organization_id=run.organization_id,
        status=response_status,
        reason={
            "passed": "production_acceptance_passed",
            "failed": "production_acceptance_failed",
            "blocked": "production_acceptance_blocked",
            "interrupted": "production_acceptance_interrupted",
            "expired": "production_acceptance_evidence_expired",
            "stale": "production_acceptance_evidence_stale",
        }.get(response_status, "production_acceptance_not_evaluated"),
        functional_acceptance=summaries["functional"],
        operational_acceptance=summaries["operational"],
        security_acceptance=summaries["security"],
        recovery_acceptance=summaries["recovery"],
        deployment_acceptance=summaries["deployment"],
        capacity_acceptance=summaries["capacity"],
        portal_acceptance=summaries["portal"],
        production_ready=production_ready,
        mandatory_gate_counts=_gate_counts(gates),
        blockers=blockers,
        warnings=warnings,
        recommendations=[
            recommendation for contract in evidence_contracts for recommendation in contract.recommendations
        ],
        next_actions=[action for contract in evidence_contracts for action in contract.next_actions],
        evidence=[ProductionAcceptanceEvidence.model_validate(row) for row in evidence],
        evidence_contracts=evidence_contracts,
        gate_results=[ProductionAcceptanceGateResult.model_validate(row) for row in gates],
        contract_version=run.contract_version,
        requested_at=run.requested_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        evaluated_at=evaluated_at,
        evaluation_timestamp=evaluated_at,
        expires_at=min(
            (item.expires_at for item in evidence_contracts if item.expires_at is not None),
            default=None,
        ),
        runtime_version="production-acceptance-runtime.v5",
        result_hash=run.result_hash,
        reused=reused,
        configuration_preflight=preflight,
    )


def _validated_evidence_contracts(
    run: ProductionAcceptanceRun,
    evidence: list[ProductionAcceptanceEvidenceModel],
    evaluated_at: datetime,
) -> list[AuthoritativeReadinessEvidence]:
    contracts: list[AuthoritativeReadinessEvidence] = []
    for item in evidence:
        if not item.evidence_type.endswith("_evidence_contract"):
            continue
        payload = item.evidence_payload if isinstance(item.evidence_payload, dict) else {}
        domain = str(payload.get("domain") or item.evidence_type.removesuffix("_evidence_contract"))
        runtime_version = str(
            payload.get("runtime_version") or SUPPORTED_DOMAIN_RUNTIME_VERSIONS.get(domain) or "unknown"
        )
        issues: list[dict[str, Any]] = []
        expected_hash = stable_hash(
            {"run_id": str(run.id), "evidence_type": item.evidence_type, "payload": item.evidence_payload}
        )
        if expected_hash != item.evidence_hash:
            issues.append(
                {
                    "code": "production_acceptance_evidence_corrupt",
                    "message": "Persisted Production Acceptance evidence hash does not match its payload.",
                    "evidence_id": str(item.id),
                }
            )
        try:
            contract = AuthoritativeReadinessEvidence.model_validate(payload)
        except ValidationError:
            contracts.append(
                build_readiness_evidence(
                    domain=domain,
                    status="failed",
                    gate_results=[],
                    blockers=issues
                    + [
                        {
                            "code": "incomplete_readiness_contract",
                            "message": "Persisted readiness contract is incomplete.",
                        }
                    ],
                    warnings=[],
                    runtime_version=runtime_version,
                    evaluation_timestamp=item.observed_at or evaluated_at,
                    expires_at=None,
                    evidence_origin=item.source_runtime or "production_acceptance_runtime",
                    integrity_errors=[
                        {"code": "invalid_contract_payload", "message": "Contract payload validation failed."}
                    ],
                )
            )
            continue
        expected_runtime = SUPPORTED_DOMAIN_RUNTIME_VERSIONS.get(contract.domain)
        if contract.contract_version != READINESS_CONTRACT_VERSION:
            issues.append(
                {
                    "code": "unsupported_contract_version",
                    "message": "Persisted readiness contract version is unsupported.",
                }
            )
        if expected_runtime is None or contract.runtime_version != expected_runtime:
            issues.append(
                {
                    "code": "incompatible_runtime_version",
                    "message": "Persisted readiness runtime version is incompatible.",
                }
            )
        if contract.evaluation_timestamp.tzinfo is None:
            issues.append(
                {"code": "invalid_evaluation_timestamp", "message": "Evaluation timestamp must include a timezone."}
            )
        if contract.expires_at is not None and contract.expires_at <= contract.evaluation_timestamp:
            issues.append(
                {"code": "invalid_evidence_lifetime", "message": "Evidence expiration must follow evaluation."}
            )
        if issues:
            contract = contract.model_copy(
                update={
                    "status": "failed",
                    "reason": "contract_hardening_failed",
                    "gate_results": [gate.model_copy(update={"status": "failed"}) for gate in contract.gate_results],
                    "blockers": [*contract.blockers, *issues],
                    "recommendations": [
                        *contract.recommendations,
                        {"code": "replace_invalid_evidence", "message": "Replace invalid persisted evidence."},
                    ],
                    "next_actions": [*contract.next_actions, {"action": "register_valid_readiness_evidence"}],
                }
            )
        elif contract.expires_at is not None and contract.expires_at <= _utcnow():
            contract = contract.model_copy(
                update={
                    "status": "expired",
                    "reason": "authoritative_evidence_expired",
                    "gate_results": [gate.model_copy(update={"status": "blocked"}) for gate in contract.gate_results],
                    "blockers": [
                        *contract.blockers,
                        {
                            "code": "readiness_evidence_expired",
                            "message": "Persisted authoritative readiness evidence has expired.",
                        },
                    ],
                    "next_actions": [*contract.next_actions, {"action": "refresh_readiness_evidence"}],
                }
            )
        contracts.append(contract)
    return contracts


def _load_result(
    db: Session,
    run: ProductionAcceptanceRun,
    *,
    preflight: ConfigurationPreflightResult | None = None,
    reused: bool = False,
) -> ProductionAcceptanceRunResult:
    repository = ProductionAcceptanceRepository(db)
    gates = repository.list_gate_results(run.id)
    evidence = repository.list_evidence(run.id)
    if preflight is None:
        persisted = next((item for item in evidence if item.evidence_type == "configuration_preflight"), None)
        if persisted is not None:
            try:
                preflight = ConfigurationPreflightResult.model_validate(persisted.evidence_payload)
            except ValidationError:
                preflight = None
    return _run_result(run, gates, evidence, preflight=preflight, reused=reused)


def run_production_acceptance(
    db: Session,
    request: ProductionAcceptanceRequest,
) -> ProductionAcceptanceRunResult:
    scope, organization_id = _normalize_request(request)
    settings = get_settings()
    preflight_evidence = refresh_configuration_preflight(
        db,
        OperationalEvidenceRequest(
            scope=scope,
            organization_id=organization_id,
            release_version=settings.app_version,
            alembic_revision=resolve_database_revision(db),
            edition=settings.platform_edition.strip().lower(),
            execution_key=build_operational_execution_key(
                "configuration_preflight",
                settings.platform_edition.strip().lower(),
                settings.app_version,
                f"production-acceptance:{request.idempotency_key}",
            ),
            correlation_id=request.correlation_id,
        ),
    )
    persisted_preflight = ReleaseOperationalEvidenceRepository(db).get(preflight_evidence.id)
    if persisted_preflight is None:
        raise ValueError("configuration_preflight_evidence_not_found")
    preflight = configuration_preflight_from_evidence(persisted_preflight)
    input_hash = _input_hash(
        scope,
        organization_id,
        request.requested_by,
        preflight_evidence.id,
    )
    if _has_idempotency_conflict(
        db,
        scope=scope,
        organization_id=organization_id,
        input_hash=input_hash,
        idempotency_key=request.idempotency_key,
    ):
        raise ValueError("idempotency_key_conflict")
    existing = _find_existing_run(
        db,
        scope=scope,
        organization_id=organization_id,
        input_hash=input_hash,
        idempotency_key=request.idempotency_key,
    )
    if existing is not None and existing.status in TERMINAL_RUN_STATUSES:
        return _load_result(db, existing, reused=True)
    run = existing
    now = _utcnow()
    if run is None:
        run = ProductionAcceptanceRun(
            correlation_id=request.correlation_id or f"production-acceptance:{uuid.uuid4()}",
            organization_id=organization_id,
            scope=scope,
            requested_by=request.requested_by,
            requested_at=now,
            status="pending",
            production_ready=False,
            contract_version=CONTRACT_VERSION,
            input_hash=input_hash,
            idempotency_key=request.idempotency_key,
        )
        db.add(run)
        db.flush()
    run.status = "running"
    run.started_at = run.started_at or now
    run.completed_at = None
    run.production_ready = False
    run.result_hash = None
    evidence_payloads = _collect_authoritative_evidence_payloads(
        db,
        organization_id=organization_id,
        configuration_preflight=preflight,
        configuration_preflight_evidence_id=preflight_evidence.id,
    )
    evidence_rows = _persist_evidence(db, run, evidence_payloads)
    gates = _persist_gate_results(db, run, evidence_payloads, evidence_rows, preflight)
    result_hash = stable_hash(_build_result_hash_payload(run, gates))
    has_failed = any(gate.status == "failed" and gate.mandatory for gate in gates)
    production_ready = production_ready_from_evidence(gates, preflight)
    run.production_ready = production_ready
    run.status = "passed" if production_ready else ("failed" if has_failed else "blocked")
    run.completed_at = _utcnow()
    run.result_hash = result_hash
    db.flush()
    evidence = list(evidence_rows.values())
    return _run_result(run, gates, evidence, preflight=preflight, reused=existing is not None)


def get_production_acceptance_run(
    db: Session,
    run_id: uuid.UUID,
    *,
    scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> ProductionAcceptanceRunResult | None:
    run = ProductionAcceptanceRepository(db).get_run(run_id, scope=scope, organization_id=organization_id)
    if run is None:
        return None
    return _load_result(
        db,
        run,
    )


def get_latest_production_acceptance(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> ProductionAcceptanceLatestResponse:
    if scope == "platform":
        organization_id = None
    run = ProductionAcceptanceRepository(db).latest_completed(
        scope=scope,
        organization_id=organization_id,
        terminal_statuses=TERMINAL_RUN_STATUSES,
    )
    if run is None:
        return ProductionAcceptanceLatestResponse(found=False, result=None, postgresql_source_of_truth=True)
    return ProductionAcceptanceLatestResponse(
        found=True,
        result=_load_result(
            db,
            run,
        ),
        postgresql_source_of_truth=True,
    )


def build_current_product_state(
    db: Session,
    result: ProductionAcceptanceRunResult | None,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> dict[str, Any]:
    settings = get_settings()
    persisted_run = (
        ProductionAcceptanceRepository(db).get_run(
            result.run_id,
            scope=scope,
            organization_id=organization_id,
        )
        if result is not None
        else None
    )
    configuration_evidence = next(
        (item for item in (result.evidence if result else []) if item.evidence_type == "configuration_preflight"),
        None,
    )
    release_evidence = None
    if configuration_evidence and configuration_evidence.source_entity_id:
        try:
            release_evidence_id = uuid.UUID(configuration_evidence.source_entity_id)
        except (TypeError, ValueError):
            release_evidence_id = None
        if release_evidence_id is not None:
            release_evidence = ReleaseOperationalEvidenceRepository(db).get(release_evidence_id)
    evidence_applicable = bool(
        release_evidence
        and release_evidence.evidence_type == "configuration_preflight"
        and release_evidence.status == "passed"
        and release_evidence.evidence_hash == stable_hash(release_evidence.evidence_payload)
        and release_evidence.scope == scope
        and release_evidence.organization_id == organization_id
    )
    return build_product_state_contract(
        result,
        persisted_run_status=persisted_run.status if persisted_run else None,
        evaluated_release_version=settings.app_version,
        evidence_release_version=release_evidence.release_version if release_evidence else None,
        evidence_applicable=evidence_applicable,
        release_evidence_expires_at=release_evidence.expires_at if release_evidence else None,
    )


def _next_actions(blockers: list[ProductionBlocker]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        action_key = NEXT_ACTIONS_BY_BLOCKER.get(blocker.code, f"resolve_{blocker.gate_code or blocker.code}".lower())
        if action_key in seen:
            continue
        seen.add(action_key)
        actions.append(
            {
                "action_key": action_key,
                "source_blocker": blocker.code,
                "domain": blocker.domain,
                "label": action_key.replace("_", " ").capitalize(),
            }
        )
    return actions


def build_production_workspace_runtime(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> ProductionWorkspaceRuntimeResponse:
    if scope == "platform":
        organization_id = None
    latest = get_latest_production_acceptance(db, scope=scope, organization_id=organization_id)
    result = latest.result
    blockers = result.blockers if result is not None else []
    warnings = result.warnings if result is not None else []
    runtime_status = "ready" if result is not None else "not_evaluated"
    if blockers:
        runtime_status = "blocked"
    domain_summary = []
    mandatory_gate_counts: dict[str, int] = {}
    production_ready = False
    if result is not None:
        domain_summary = [
            result.functional_acceptance,
            result.operational_acceptance,
            result.security_acceptance,
            result.recovery_acceptance,
            result.deployment_acceptance,
            result.capacity_acceptance,
            result.portal_acceptance,
        ]
        mandatory_gate_counts = result.mandatory_gate_counts
        production_ready = result.production_ready
    contracts = {item.domain: item.model_dump(mode="json") for item in (result.evidence_contracts if result else [])}
    functional = contracts.get("local_product_acceptance", {})
    product_state = build_current_product_state(
        db,
        result,
        scope=scope,
        organization_id=organization_id,
    )
    release_eligibility = product_state["release_eligibility"]
    return ProductionWorkspaceRuntimeResponse(
        runtime_status=runtime_status,
        current_status=str(release_eligibility["status"]),
        local_product_acceptance=functional,
        product_acceptance=product_state["product_acceptance"],
        evidence_freshness=product_state["evidence_freshness"],
        release_eligibility=release_eligibility,
        release_candidate_eligible=bool(release_eligibility["eligible"]),
        production_ready=production_ready,
        latest_run=result,
        domain_summary=domain_summary,
        mandatory_gate_counts=mandatory_gate_counts,
        blockers=blockers,
        warnings=warnings,
        configuration_preflight=result.configuration_preflight if result else None,
        operational_readiness=contracts.get("observability", {}),
        security_readiness=contracts.get("security", {}),
        recovery_readiness=contracts.get("recovery", {}),
        deployment_readiness=contracts.get("release_governance", {}),
        capacity_readiness=contracts.get("capacity", {}),
        next_actions=_next_actions(blockers),
        postgresql_source_of_truth=True,
        llm_used=False,
        qdrant_used=False,
    )
