from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AuditEvent
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.models.security_acceptance import SecurityEvidence, SecurityFinding, SecurityPolicyRuntime
from app.repositories.security_acceptance import SecurityAcceptanceRepository
from app.schemas.security_acceptance import (
    SecurityConfigurationCheck,
    SecurityConfigurationResponse,
    SecurityEvidenceRead,
    SecurityFindingRead,
    SecurityPolicyCreate,
    SecurityPolicyRead,
    SecurityPolicyUpdate,
    SecurityReadinessGate,
    SecurityReadinessResponse,
    SecurityWorkspaceRuntimeResponse,
)
from app.services.configuration_preflight import (
    build_configuration_evidence_contract,
    is_placeholder_value,
    mask_setting_value,
)
from app.services.readiness_contract import build_readiness_evidence

DEFAULT_FRESHNESS_HOURS = 24
SUPERSEDED_CONFIGURATION_RULES = {"cors_allowed_origins"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_safe_json(item) for item in value]
    return value


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(_safe_json(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _count(db: Session, model: Any, *criteria: Any) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _scope(scope: str, organization_id: uuid.UUID | None) -> tuple[str, uuid.UUID | None]:
    return ("platform", None) if scope == "platform" else ("organization", organization_id)


def mask_value(key: str, value: Any) -> str:
    return mask_setting_value(key, value)


def _is_placeholder(value: Any) -> bool:
    return is_placeholder_value(value)


def scan_security_configuration() -> list[SecurityConfigurationCheck]:
    categories = {
        "object_storage_endpoint_url": "object_storage",
        "object_storage_bucket": "object_storage",
        "object_storage_access_key": "object_storage",
        "object_storage_secret_key": "object_storage",
        "object_storage_tls": "object_storage",
        "authentication": "authentication",
        "cors": "cors",
        "debug": "debug",
        "database_url": "database",
        "secret_store_provider": "secrets",
        "feature_embeddings_enabled": "ai",
        "feature_vector_retrieval_enabled": "ai",
        "provider_execution_explicit": "providers",
        "ai_optional": "ai",
    }
    security_codes = {
        "cors": "cors_restricted",
        "debug": "debug_disabled",
    }
    return [
        SecurityConfigurationCheck(
            setting_code=security_codes.get(check.setting_code, check.setting_code),
            category=categories[check.setting_code],
            status=check.status,
            masked_value=check.masked_value,
            reason=check.reason,
            mandatory=check.mandatory,
            configured=check.configured,
            placeholder=check.placeholder,
            evidence_origin=check.evidence_origin,
            evaluated_at=check.evaluated_at,
        )
        for check in build_configuration_evidence_contract()
    ]


def create_security_policy(db: Session, payload: SecurityPolicyCreate) -> SecurityPolicyRead:
    repo = SecurityAcceptanceRepository(db)
    existing = next(
        (
            item
            for item in repo.list_policies(payload.scope, payload.organization_id)
            if item.policy_code == payload.policy_code
        ),
        None,
    )
    if existing is not None:
        fields = payload.model_dump().keys()
        persisted = {field: getattr(existing, field) for field in fields}
        if stable_hash(_safe_json(persisted)) != stable_hash(_safe_json(payload.model_dump())):
            raise ValueError("security_policy_conflict")
        return SecurityPolicyRead.model_validate(existing)
    policy = SecurityPolicyRuntime(**payload.model_dump())
    db.add(policy)
    db.flush()
    return SecurityPolicyRead.model_validate(policy)


def update_security_policy(
    db: Session, policy: SecurityPolicyRuntime, payload: SecurityPolicyUpdate
) -> SecurityPolicyRead:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, key, value)
    db.add(policy)
    db.flush()
    return SecurityPolicyRead.model_validate(policy)


def activate_security_policy(db: Session, policy: SecurityPolicyRuntime) -> SecurityPolicyRead:
    repo = SecurityAcceptanceRepository(db)
    for item in repo.list_policies(policy.scope, policy.organization_id):
        if item.id != policy.id and item.status == "active":
            item.status = "inactive"
            item.deactivated_at = _utcnow()
            db.add(item)
    policy.status = "active"
    policy.activated_at = _utcnow()
    policy.deactivated_at = None
    db.add(policy)
    db.flush()
    return SecurityPolicyRead.model_validate(policy)


def _persist_evidence(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    evidence_type: str,
    status: str,
    payload: dict[str, Any],
    freshness_hours: float,
    source_entity_type: str = "security_check",
    source_entity_id: str | None = None,
) -> SecurityEvidence:
    repo = SecurityAcceptanceRepository(db)
    clean_payload = _safe_json(payload)
    evidence_hash = stable_hash({"evidence_type": evidence_type, "payload": clean_payload, "status": status})
    existing = repo.find_evidence(
        scope,
        organization_id,
        evidence_type,
        "security_acceptance_runtime",
        source_entity_type,
        source_entity_id,
        evidence_hash,
    )
    if existing is not None:
        observed_at = _utcnow()
        existing.observed_at = observed_at
        existing.expires_at = observed_at + timedelta(hours=freshness_hours)
        db.add(existing)
        db.flush()
        return existing
    observed_at = _utcnow()
    evidence = SecurityEvidence(
        scope=scope,
        organization_id=organization_id,
        evidence_type=evidence_type,
        source_runtime="security_acceptance_runtime",
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        status=status,
        evidence_payload=clean_payload,
        evidence_hash=evidence_hash,
        observed_at=observed_at,
        expires_at=observed_at + timedelta(hours=freshness_hours),
    )
    db.add(evidence)
    db.flush()
    return evidence


def _persist_finding(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    rule: str,
    category: str,
    severity: str,
    summary: str,
    evidence: dict[str, Any],
    remediation: str,
) -> SecurityFinding:
    repo = SecurityAcceptanceRepository(db)
    evidence_hash = stable_hash({"rule": rule, "evidence": _safe_json(evidence)})
    existing = repo.find_finding(
        scope,
        organization_id,
        rule,
        "security_acceptance_runtime",
        "configuration",
        rule,
        evidence_hash,
    )
    if existing is not None:
        existing.last_observed_at = _utcnow()
        existing.status = "open"
        existing.resolved_at = None
        db.add(existing)
        db.flush()
        return existing
    finding = SecurityFinding(
        scope=scope,
        organization_id=organization_id,
        rule=rule,
        category=category,
        severity=severity,
        status="open",
        summary=summary,
        evidence=_safe_json(evidence),
        remediation=remediation,
        source_runtime="security_acceptance_runtime",
        source_entity_type="configuration",
        source_entity_id=rule,
        evidence_hash=evidence_hash,
    )
    db.add(finding)
    db.flush()
    return finding


def _policy_freshness_hours(policy: SecurityPolicyRuntime | None) -> float:
    if policy is None:
        return DEFAULT_FRESHNESS_HOURS
    for payload in (policy.configuration_payload, policy.audit_requirements):
        configured = payload.get("evidence_max_age_hours") if isinstance(payload, dict) else None
        try:
            freshness_hours = float(configured)
        except (TypeError, ValueError):
            continue
        if freshness_hours > 0:
            return freshness_hours
    return DEFAULT_FRESHNESS_HOURS


def _finding_evidence(check: SecurityConfigurationCheck) -> dict[str, Any]:
    return {
        "setting_code": check.setting_code,
        "masked_value": check.masked_value,
        "reason": check.reason,
        "configured": check.configured,
        "placeholder": check.placeholder,
        "evidence_origin": check.evidence_origin,
    }


def _reconcile_configuration_findings(
    db: Session,
    repo: SecurityAcceptanceRepository,
    scope: str,
    organization_id: uuid.UUID | None,
    checks: list[SecurityConfigurationCheck],
) -> None:
    current_hashes = {
        check.setting_code: stable_hash(
            {"rule": check.setting_code, "evidence": _safe_json(_finding_evidence(check))}
        )
        for check in checks
        if check.status in {"failed", "blocked"}
    }
    evaluated_rules = {check.setting_code for check in checks} | SUPERSEDED_CONFIGURATION_RULES
    resolved_at = _utcnow()
    for finding in repo.list_findings(scope, organization_id):
        if (
            finding.source_runtime != "security_acceptance_runtime"
            or finding.source_entity_type != "configuration"
            or finding.rule not in evaluated_rules
            or finding.status not in {"open", "acknowledged"}
        ):
            continue
        if current_hashes.get(finding.rule) == finding.evidence_hash:
            continue
        finding.status = "resolved"
        finding.resolved_at = resolved_at
        db.add(finding)
    db.flush()


def evaluate_security_configuration(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> SecurityConfigurationResponse:
    scope, organization_id = _scope(scope, organization_id)
    repo = SecurityAcceptanceRepository(db)
    policy = repo.active_policy(scope, organization_id)
    freshness_hours = _policy_freshness_hours(policy)
    checks = scan_security_configuration()
    _reconcile_configuration_findings(db, repo, scope, organization_id, checks)
    findings: list[SecurityFinding] = []
    for check in checks:
        if check.status in {"failed", "blocked"}:
            findings.append(
                _persist_finding(
                    db,
                    scope=scope,
                    organization_id=organization_id,
                    rule=check.setting_code,
                    category=check.category,
                    severity="critical" if check.status == "failed" else "high",
                    summary=f"Security configuration check {check.setting_code} is {check.status}.",
                    evidence=_finding_evidence(check),
                    remediation=f"Configure {check.setting_code} with a safe explicit value.",
                )
            )
        _persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type=check.setting_code,
            status=check.status,
            payload=check.model_dump(mode="json", exclude={"evaluated_at"}),
            freshness_hours=freshness_hours,
            source_entity_id=check.setting_code,
        )
    return SecurityConfigurationResponse(
        profile=get_settings().environment_profile or "development",
        checks=checks,
        findings=[SecurityFindingRead.model_validate(item) for item in findings],
    )


def _security_management_evidence(db: Session, scope: str, organization_id: uuid.UUID | None) -> dict[str, Any]:
    if organization_id is None:
        roles = _count(db, Role)
        permissions = _count(db, Permission)
        policies = _count(db, Policy)
        assignment_filter: tuple[Any, ...] = ()
    else:
        roles = _count(db, Role, Role.organization_id == organization_id)
        permissions = int(
            db.scalar(
                select(func.count(func.distinct(Permission.id)))
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(Role, Role.id == RolePermission.role_id)
                .where(Role.organization_id == organization_id)
            )
            or 0
        )
        policies = _count(db, Policy, Policy.organization_id == organization_id)
        assignment_filter = (RoleAssignment.organization_id == organization_id,)
    return {
        "roles": roles,
        "permissions": permissions,
        "policies": policies,
        "active_assignments": _count(
            db,
            RoleAssignment,
            RoleAssignment.status == "active",
            *assignment_filter,
        ),
    }


def _audit_evidence(db: Session, organization_id: uuid.UUID | None) -> dict[str, Any]:
    criteria = (AuditEvent.organization_id == organization_id,) if organization_id is not None else ()
    return {"audit_events": _count(db, AuditEvent, *criteria)}


def _evidence_by_type(evidence: list[SecurityEvidence]) -> dict[str, SecurityEvidence]:
    output: dict[str, SecurityEvidence] = {}
    for item in sorted(evidence, key=lambda row: row.observed_at, reverse=True):
        output.setdefault(item.evidence_type, item)
    return output


def _gate(
    code: str,
    status: str,
    summary: str,
    evidence: SecurityEvidence | None = None,
    *,
    warning: str | None = None,
) -> SecurityReadinessGate:
    blocking = [] if status == "passed" else [{"code": f"{code}_blocked", "message": summary}]
    warnings = [{"code": f"{code}_warning", "message": warning}] if warning else []
    return SecurityReadinessGate(
        gate_code=code,
        status=status,
        summary=summary,
        evidence_type=evidence.evidence_type if evidence else code,
        evidence_reference=str(evidence.id) if evidence else None,
        blocking_issues=blocking,
        warnings=warnings,
    )


def build_security_readiness(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    *,
    refresh: bool = True,
) -> SecurityReadinessResponse:
    scope, organization_id = _scope(scope, organization_id)
    repo = SecurityAcceptanceRepository(db)
    policy = repo.active_policy(scope, organization_id)
    freshness_hours = _policy_freshness_hours(policy)
    if refresh:
        evaluate_security_configuration(db, scope, organization_id)
        management = _security_management_evidence(db, scope, organization_id)
        audit = _audit_evidence(db, organization_id)
        _persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="authorization_configured",
            status="passed" if management["permissions"] > 0 and management["active_assignments"] > 0 else "blocked",
            payload=management,
            freshness_hours=freshness_hours,
            source_entity_id="authorization_configured",
        )
        _persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="authentication_configured",
            status="passed" if management["active_assignments"] > 0 else "blocked",
            payload={"active_assignments": management["active_assignments"]},
            freshness_hours=freshness_hours,
            source_entity_id="authentication_configured",
        )
        _persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="organization_isolation_verified",
            status="passed" if management["active_assignments"] > 0 else "blocked",
            payload={"scope": scope, "organization_id": str(organization_id) if organization_id else None},
            freshness_hours=freshness_hours,
            source_entity_id="organization_isolation_verified",
        )
        _persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="audit_runtime_available",
            status="passed" if audit["audit_events"] > 0 else "blocked",
            payload=audit,
            freshness_hours=freshness_hours,
            source_entity_id="audit_runtime_available",
        )
    evidence = repo.list_evidence(scope, organization_id)
    findings = repo.list_findings(scope, organization_id)
    latest = _evidence_by_type(evidence)
    contract_evidence = list(latest.values())
    checks = scan_security_configuration() if refresh else []
    placeholder_failures = [check for check in checks if check.reason == "placeholder_detected"]
    if not refresh:
        placeholder_failures = [
            item
            for item in findings
            if item.status in {"open", "acknowledged"}
            and item.rule == "secret_placeholders_absent"
        ]
    auth = latest.get("authentication_configured")
    audit = latest.get("audit_runtime_available")
    isolation = latest.get("organization_isolation_verified")
    debug = latest.get("debug_disabled")
    cors = latest.get("cors_restricted")
    providers = latest.get("provider_execution_explicit")
    failed_findings = [
        item for item in findings if item.status in {"open", "acknowledged"} and item.severity in {"high", "critical"}
    ]
    gates = [
        _gate(
            "production_authentication_required",
            "passed" if auth and auth.status == "passed" else "blocked",
            "Authentication has persisted security evidence."
            if auth and auth.status == "passed"
            else "Authentication evidence is missing.",
            auth,
        ),
        _gate(
            "production_configuration_fail_closed",
            "passed"
            if policy
            and policy.status == "active"
            and policy.authentication_required
            and policy.authorization_required
            and not policy.debug_allowed
            else "blocked",
            "Active policy requires authentication, authorization and debug disabled."
            if policy
            and policy.status == "active"
            and policy.authentication_required
            and policy.authorization_required
            and not policy.debug_allowed
            else "No active fail-closed security policy is persisted.",
        ),
        _gate(
            "secret_placeholders_absent",
            "failed" if placeholder_failures else "passed",
            "No placeholder secrets were detected."
            if not placeholder_failures
            else "Placeholder-like configuration values were detected.",
            latest.get("secret_placeholders_absent"),
        ),
        _gate(
            "cross_organization_access_blocked",
            "passed" if isolation and isolation.status == "passed" else "blocked",
            "Organization isolation has persisted evidence."
            if isolation and isolation.status == "passed"
            else "Organization isolation evidence is missing.",
            isolation,
        ),
        _gate(
            "audit_runtime_available",
            "passed" if audit and audit.status == "passed" else "blocked",
            "Audit runtime has persisted events."
            if audit and audit.status == "passed"
            else "Audit runtime evidence is missing.",
            audit,
        ),
        _gate(
            "debug_disabled",
            "passed" if debug and debug.status == "passed" else "blocked",
            "Debug exposure is disabled."
            if debug and debug.status == "passed"
            else "Debug disabled evidence is missing.",
            debug,
        ),
        _gate(
            "cors_restricted",
            "passed" if cors and cors.status == "passed" else "failed",
            "CORS origins are restricted." if cors and cors.status == "passed" else "CORS restriction evidence failed.",
            cors,
        ),
        _gate(
            "provider_execution_explicit",
            "passed" if providers and providers.status == "passed" else "blocked",
            "Provider execution is explicit and AI remains optional."
            if providers and providers.status == "passed"
            else "Provider execution evidence is missing.",
            providers,
        ),
    ]
    gates.append(
        _gate(
            "security_findings_clear",
            "failed" if failed_findings else "passed",
            "Open high or critical security findings are present."
            if failed_findings
            else "No open high or critical security findings are present.",
            warning="Resolve or suppress high and critical findings with evidence."
            if failed_findings
            else None,
        )
    )
    expired_ids = {
        str(item.id)
        for item in contract_evidence
        if item.expires_at is not None and item.expires_at <= _utcnow()
    }
    if expired_ids:
        gates = [
            gate.model_copy(
                update={
                    "status": "blocked",
                    "summary": "Persisted security evidence is expired.",
                    "blocking_issues": [
                        {"code": "security_evidence_expired", "message": "Persisted security evidence is expired."}
                    ],
                }
            )
            if gate.evidence_reference in expired_ids
            else gate
            for gate in gates
        ]
    blockers = [issue for gate in gates for issue in gate.blocking_issues]
    warnings = [warning for gate in gates for warning in gate.warnings]
    security_ready = bool(gates) and all(gate.status == "passed" for gate in gates)
    status = "passed" if security_ready else ("failed" if any(gate.status == "failed" for gate in gates) else "blocked")
    next_actions = _security_next_actions(gates)
    evidence_timestamps = [item.observed_at for item in contract_evidence]
    evidence_expirations = [item.expires_at for item in contract_evidence if item.expires_at is not None]
    integrity_errors = [
        {
            "code": "security_evidence_corrupt",
            "message": "Persisted security evidence hash does not match its payload.",
            "evidence_id": str(item.id),
        }
        for item in contract_evidence
        if stable_hash(
            {"evidence_type": item.evidence_type, "payload": _safe_json(item.evidence_payload), "status": item.status}
        )
        != item.evidence_hash
    ]
    evidence_contract = build_readiness_evidence(
        domain="security",
        status="expired" if expired_ids else status,
        gate_results=gates,
        blockers=blockers,
        warnings=warnings,
        next_actions=next_actions,
        runtime_version="security-acceptance-runtime.v1",
        evaluation_timestamp=max(evidence_timestamps) if evidence_timestamps else None,
        expires_at=min(evidence_expirations) if evidence_expirations else None,
        evidence_origin="security_acceptance_runtime",
        components_evaluated=[item.evidence_type for item in contract_evidence],
        evidence_ids=[str(item.id) for item in contract_evidence],
        source_runtime_version="security-acceptance-runtime.v1",
        supported_runtime_versions=("security-acceptance-runtime.v1",),
        integrity_errors=integrity_errors,
    )
    return SecurityReadinessResponse(
        runtime_status="ready",
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        security_ready=evidence_contract.status == "passed",
        gates=gates,
        policy=SecurityPolicyRead.model_validate(policy) if policy else None,
        configuration_checks=checks,
        findings=[SecurityFindingRead.model_validate(item) for item in findings[:50]],
        evidence=[SecurityEvidenceRead.model_validate(item) for item in evidence[:50]],
        blockers=evidence_contract.blockers,
        warnings=evidence_contract.warnings,
        recommendations=evidence_contract.recommendations,
        next_actions=evidence_contract.next_actions,
        evidence_contract=evidence_contract,
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
    )


def _security_next_actions(gates: list[SecurityReadinessGate]) -> list[dict[str, Any]]:
    mapping = {
        "production_authentication_required": "configure_authentication",
        "production_configuration_fail_closed": "activate_fail_closed_security_policy",
        "secret_placeholders_absent": "replace_placeholder_secrets",
        "cross_organization_access_blocked": "validate_organization_isolation",
        "audit_runtime_available": "enable_audit_evidence",
        "debug_disabled": "disable_debug_exposure",
        "cors_restricted": "restrict_cors_origins",
        "provider_execution_explicit": "configure_provider_execution_policy",
        "security_findings_clear": "resolve_security_findings",
    }
    return [
        {
            "action": mapping.get(gate.gate_code, "review_security_gate"),
            "source_gate": gate.gate_code,
            "status": gate.status,
            "summary": gate.summary,
        }
        for gate in gates
        if gate.status != "passed"
    ]


def build_security_configuration(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> SecurityConfigurationResponse:
    return evaluate_security_configuration(db, scope, organization_id)


def build_security_workspace_runtime(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    *,
    refresh: bool = True,
) -> SecurityWorkspaceRuntimeResponse:
    scope, organization_id = _scope(scope, organization_id)
    repo = SecurityAcceptanceRepository(db)
    readiness = build_security_readiness(db, scope, organization_id, refresh=refresh)
    policies = repo.list_policies(scope, organization_id)
    findings = repo.list_findings(scope, organization_id)
    evidence = repo.list_evidence(scope, organization_id)
    checks = readiness.configuration_checks
    return SecurityWorkspaceRuntimeResponse(
        runtime_status="ready",
        readiness=readiness,
        policies=[SecurityPolicyRead.model_validate(item) for item in policies],
        findings=[SecurityFindingRead.model_validate(item) for item in findings[:50]],
        evidence=[SecurityEvidenceRead.model_validate(item) for item in evidence[:50]],
        configuration_summary={
            "check_count": len(checks),
            "passed": len([item for item in checks if item.status == "passed"]),
            "failed": len([item for item in checks if item.status == "failed"]),
            "blocked": len([item for item in checks if item.status == "blocked"]),
            "not_evaluated": len([item for item in checks if item.status == "not_evaluated"]),
        },
        severity_summary=dict(Counter(item.severity for item in findings)),
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        next_actions=readiness.next_actions,
    )
