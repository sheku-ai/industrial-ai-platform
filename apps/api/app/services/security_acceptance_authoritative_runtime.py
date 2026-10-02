from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product_acceptance import AcceptanceExecution, AcceptanceGate
from app.models.security_acceptance import SecurityFinding
from app.repositories.security_acceptance import SecurityAcceptanceRepository
from app.schemas.security_acceptance import (
    SecurityConfigurationCheck,
    SecurityConfigurationResponse,
    SecurityEvidenceRead,
    SecurityFindingRead,
    SecurityPolicyRead,
    SecurityReadinessResponse,
    SecurityWorkspaceRuntimeResponse,
)
from app.services import security_acceptance_runtime as legacy
from app.services.configuration_preflight import (
    build_configuration_evidence_contract,
    build_configuration_preflight,
)

activate_security_policy = legacy.activate_security_policy
create_security_policy = legacy.create_security_policy
update_security_policy = legacy.update_security_policy

_CONFIGURATION_CATEGORIES = {
    "object_storage_endpoint_url": "object_storage",
    "object_storage_bucket": "object_storage",
    "object_storage_access_key": "object_storage",
    "object_storage_secret_key": "object_storage",
    "object_storage_tls": "object_storage",
    "authentication": "authentication",
    "identity_database_url": "authentication",
    "authentication_cookie_secure": "authentication",
    "cors": "cors",
    "debug": "debug",
    "database_url": "database",
    "secret_store_provider": "secrets",
    "feature_embeddings_enabled": "ai",
    "feature_vector_retrieval_enabled": "ai",
    "provider_execution_explicit": "providers",
    "ai_optional": "ai",
}

_SECURITY_CODES = {
    "cors": "cors_restricted",
    "debug": "debug_disabled",
}

_AUTHENTICATION_CONFIGURATION_CODES = (
    "authentication",
    "identity_database_url",
    "authentication_cookie_secure",
)


def _scope(scope: str, organization_id: uuid.UUID | None) -> tuple[str, uuid.UUID | None]:
    return legacy._scope(scope, organization_id)


def scan_security_configuration() -> list[SecurityConfigurationCheck]:
    checks = build_configuration_evidence_contract()
    return [
        SecurityConfigurationCheck(
            setting_code=_SECURITY_CODES.get(check.setting_code, check.setting_code),
            category=_CONFIGURATION_CATEGORIES[check.setting_code],
            status=check.status,
            masked_value=check.masked_value,
            reason=check.reason,
            mandatory=check.mandatory,
            configured=check.configured,
            placeholder=check.placeholder,
            evidence_origin=check.evidence_origin,
            evaluated_at=check.evaluated_at,
        )
        for check in checks
    ]


def _authentication_configuration_evidence() -> tuple[str, dict[str, Any]]:
    checks = {check.setting_code: check for check in build_configuration_evidence_contract()}
    required = [checks.get(code) for code in _AUTHENTICATION_CONFIGURATION_CODES]
    passed = all(check is not None and check.status == "passed" for check in required)
    payload = {
        "required_checks": {
            code: {
                "status": checks[code].status if code in checks else "missing",
                "reason": checks[code].reason if code in checks else "missing",
                "evidence_origin": checks[code].evidence_origin if code in checks else None,
            }
            for code in _AUTHENTICATION_CONFIGURATION_CODES
        },
        "authority": "configuration_preflight.get_settings",
    }
    return ("passed" if passed else "blocked"), payload


def _latest_negative_isolation_gate(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
) -> tuple[AcceptanceGate, AcceptanceExecution] | None:
    statement = (
        select(AcceptanceGate, AcceptanceExecution)
        .join(AcceptanceExecution, AcceptanceExecution.id == AcceptanceGate.execution_id)
        .where(
            AcceptanceGate.gate_code == "negative_org_isolation",
            AcceptanceGate.status == "PASSED",
            AcceptanceExecution.status.in_(("PASSED", "PASSED_WITH_WARNINGS")),
        )
        .order_by(
            AcceptanceGate.completed_at.desc().nullslast(),
            AcceptanceExecution.completed_at.desc().nullslast(),
            AcceptanceGate.updated_at.desc(),
        )
    )
    if scope == "organization" and organization_id is not None:
        statement = statement.where(AcceptanceExecution.organization_id == organization_id)
    row = db.execute(statement.limit(1)).first()
    if row is None:
        return None
    return row[0], row[1]


def _organization_isolation_evidence(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
) -> tuple[str, dict[str, Any], str | None]:
    persisted = _latest_negative_isolation_gate(db, scope, organization_id)
    if persisted is None:
        return (
            "blocked",
            {
                "gate_code": "negative_org_isolation",
                "reason": "persisted_product_acceptance_gate_missing",
                "scope": scope,
                "organization_id": str(organization_id) if organization_id else None,
            },
            None,
        )
    gate, execution = persisted
    return (
        "passed",
        {
            "gate_code": gate.gate_code,
            "gate_status": gate.status,
            "gate_id": str(gate.id),
            "execution_id": str(execution.id),
            "execution_key": execution.execution_key,
            "execution_status": execution.status,
            "scenario": execution.scenario,
            "organization_id": str(execution.organization_id) if execution.organization_id else None,
            "completed_at": gate.completed_at.isoformat() if gate.completed_at else None,
            "details": legacy._safe_json(gate.details),
            "authority": "runtime.acceptance_gates",
        },
        str(gate.id),
    )


def _resolve_preflight_finding(
    db: Session,
    repo: SecurityAcceptanceRepository,
    scope: str,
    organization_id: uuid.UUID | None,
) -> None:
    resolved_at = legacy._utcnow()
    for finding in repo.list_findings(scope, organization_id):
        if (
            finding.rule == "production_configuration_preflight"
            and finding.source_runtime == "security_acceptance_runtime"
            and finding.status in {"open", "acknowledged"}
        ):
            finding.status = "resolved"
            finding.resolved_at = resolved_at
            db.add(finding)
    db.flush()


def _persist_production_preflight(
    db: Session,
    scope: str,
    organization_id: uuid.UUID | None,
    freshness_hours: float,
) -> None:
    repo = SecurityAcceptanceRepository(db)
    preflight = build_configuration_preflight("production", db=db, probe_dependencies=False)
    payload = preflight.model_dump(mode="json")
    status = "passed" if preflight.status == "passed" else "failed"
    legacy._persist_evidence(
        db,
        scope=scope,
        organization_id=organization_id,
        evidence_type="production_configuration_preflight",
        status=status,
        payload=payload,
        freshness_hours=freshness_hours,
        source_entity_type="configuration_preflight",
        source_entity_id="production",
    )
    if status == "passed":
        _resolve_preflight_finding(db, repo, scope, organization_id)
        return
    legacy._persist_finding(
        db,
        scope=scope,
        organization_id=organization_id,
        rule="production_configuration_preflight",
        category="configuration",
        severity="critical",
        summary="Production configuration preflight is not passing.",
        evidence={
            "status": preflight.status,
            "blockers": legacy._safe_json(preflight.blockers),
            "warnings": legacy._safe_json(preflight.warnings),
        },
        remediation="Resolve the production configuration preflight blockers before release.",
    )


def evaluate_security_configuration(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> SecurityConfigurationResponse:
    scope, organization_id = _scope(scope, organization_id)
    repo = SecurityAcceptanceRepository(db)
    policy = repo.active_policy(scope, organization_id)
    freshness_hours = legacy._policy_freshness_hours(policy)
    checks = scan_security_configuration()
    legacy._reconcile_configuration_findings(db, repo, scope, organization_id, checks)
    findings: list[SecurityFinding] = []
    for check in checks:
        if check.status in {"failed", "blocked"}:
            findings.append(
                legacy._persist_finding(
                    db,
                    scope=scope,
                    organization_id=organization_id,
                    rule=check.setting_code,
                    category=check.category,
                    severity="critical" if check.status == "failed" else "high",
                    summary=f"Security configuration check {check.setting_code} is {check.status}.",
                    evidence=legacy._finding_evidence(check),
                    remediation=f"Configure {check.setting_code} with a safe explicit value.",
                )
            )
        legacy._persist_evidence(
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
        profile=legacy.get_settings().environment_profile or "development",
        checks=checks,
        findings=[SecurityFindingRead.model_validate(item) for item in findings],
    )


def build_security_configuration(
    db: Session,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> SecurityConfigurationResponse:
    return evaluate_security_configuration(db, scope, organization_id)


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
    freshness_hours = legacy._policy_freshness_hours(policy)
    checks: list[SecurityConfigurationCheck] = []
    if refresh:
        configuration = evaluate_security_configuration(db, scope, organization_id)
        checks = configuration.checks
        management = legacy._security_management_evidence(db, scope, organization_id)
        audit = legacy._audit_evidence(db, organization_id)
        legacy._persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="authorization_configured",
            status="passed" if management["permissions"] > 0 and management["active_assignments"] > 0 else "blocked",
            payload=management,
            freshness_hours=freshness_hours,
            source_entity_id="authorization_configured",
        )
        auth_status, auth_payload = _authentication_configuration_evidence()
        legacy._persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="authentication_configured",
            status=auth_status,
            payload=auth_payload,
            freshness_hours=freshness_hours,
            source_entity_type="configuration_preflight",
            source_entity_id="authentication",
        )
        isolation_status, isolation_payload, isolation_gate_id = _organization_isolation_evidence(
            db, scope, organization_id
        )
        legacy._persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="organization_isolation_verified",
            status=isolation_status,
            payload=isolation_payload,
            freshness_hours=freshness_hours,
            source_entity_type="acceptance_gate",
            source_entity_id=isolation_gate_id or "negative_org_isolation",
        )
        legacy._persist_evidence(
            db,
            scope=scope,
            organization_id=organization_id,
            evidence_type="audit_runtime_available",
            status="passed" if audit["audit_events"] > 0 else "blocked",
            payload=audit,
            freshness_hours=freshness_hours,
            source_entity_id="audit_runtime_available",
        )
        _persist_production_preflight(db, scope, organization_id, freshness_hours)

    readiness = legacy.build_security_readiness(
        db,
        scope=scope,
        organization_id=organization_id,
        refresh=False,
    )
    return readiness.model_copy(update={"configuration_checks": checks}) if refresh else readiness


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
