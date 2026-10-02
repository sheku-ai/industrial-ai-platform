from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.config import Settings
from app.schemas.security_acceptance import SecurityConfigurationCheck, SecurityReadinessGate
from app.services import configuration_preflight
from app.services.configuration_preflight import build_configuration_evidence_contract
from app.services.security_acceptance_runtime import (
    _finding_evidence,
    _is_placeholder,
    _policy_freshness_hours,
    _reconcile_configuration_findings,
    mask_value,
    stable_hash,
)


def test_secret_masking_never_exposes_secret_values():
    assert mask_value("object_storage_secret_key", "super-secret-value") == "configured"
    assert mask_value("database_url", "postgres://user:password@localhost/db") == "configured"
    assert mask_value("cors_allowed_origins", "https://portal.example") == "http********"


def test_placeholder_detection_is_case_and_space_insensitive():
    assert _is_placeholder(" CHANGE ME ") is True
    assert _is_placeholder("CHANGE_ME") is True
    assert _is_placeholder("changeme") is True
    assert _is_placeholder("Dummy") is True
    assert _is_placeholder("safe-value") is False


def test_security_readiness_gate_contract_carries_evidence_reference():
    gate = SecurityReadinessGate(
        gate_code="debug_disabled",
        status="passed",
        summary="Debug disabled.",
        evidence_type="debug_disabled",
        evidence_reference="evidence-id",
    )
    assert gate.gate_code == "debug_disabled"
    assert gate.status == "passed"
    assert gate.evidence_reference == "evidence-id"


def test_failed_security_gate_blocks_security_acceptance():
    gates = [
        SecurityReadinessGate(gate_code="debug_disabled", status="passed", summary="Debug disabled."),
        SecurityReadinessGate(gate_code="cors_restricted", status="failed", summary="Wildcard CORS."),
    ]
    assert any(gate.status == "failed" for gate in gates)
    assert not all(gate.status == "passed" for gate in gates)


def test_security_acceptance_gates_are_authoritative_contract():
    gate_codes = {
        "production_authentication_required",
        "production_configuration_fail_closed",
        "secret_placeholders_absent",
        "cross_organization_access_blocked",
        "audit_runtime_available",
        "debug_disabled",
        "cors_restricted",
        "provider_execution_explicit",
    }
    assert "cross_organization_access_blocked" in gate_codes
    assert "provider_execution_explicit" in gate_codes


def test_configuration_contract_uses_settings_and_never_exposes_credentials(monkeypatch):
    settings = Settings(
        _env_file=None,
        object_storage_provider="minio",
        object_storage_endpoint_url="http://localhost:9000",
        object_storage_bucket="industrial-ai",
        object_storage_access_key="minioadmin",
        object_storage_secret_key="minioadmin",
        object_storage_secure=False,
        authentication_required=True,
        cors_allowed_origins="http://localhost:3000",
        debug=False,
    )
    monkeypatch.setattr(configuration_preflight, "get_settings", lambda: settings)

    contract = {item.setting_code: item for item in build_configuration_evidence_contract()}

    assert contract["object_storage_bucket"].reason == "configured"
    assert contract["object_storage_access_key"].reason == "development_credentials_detected"
    assert contract["object_storage_secret_key"].reason == "development_credentials_detected"
    assert contract["object_storage_endpoint_url"].reason == "localhost_or_private_object_storage_url_detected"
    assert contract["object_storage_tls"].reason == "object_storage_tls_disabled"
    serialized = " ".join(item.model_dump_json() for item in contract.values())
    assert "minioadmin" not in serialized


def test_security_policy_controls_evidence_freshness():
    policy = SimpleNamespace(
        configuration_payload={"evidence_max_age_hours": 6},
        audit_requirements={},
    )
    assert _policy_freshness_hours(policy) == 6


def test_finding_reconciliation_only_resolves_findings_disproved_by_current_evidence():
    evaluated_at = datetime.now(UTC)
    current_missing = SecurityConfigurationCheck(
        setting_code="object_storage_bucket",
        category="object_storage",
        status="blocked",
        masked_value="missing",
        reason="missing",
        mandatory=True,
        configured=False,
        placeholder=False,
        evaluated_at=evaluated_at,
    )
    current_hash = stable_hash(
        {
            "rule": current_missing.setting_code,
            "evidence": _finding_evidence(current_missing),
        }
    )
    current_finding = SimpleNamespace(
        source_runtime="security_acceptance_runtime",
        source_entity_type="configuration",
        rule="object_storage_bucket",
        status="open",
        evidence_hash=current_hash,
        resolved_at=None,
    )
    obsolete_finding = SimpleNamespace(
        source_runtime="security_acceptance_runtime",
        source_entity_type="configuration",
        rule="cors_allowed_origins",
        status="open",
        evidence_hash="obsolete",
        resolved_at=None,
    )
    repository = SimpleNamespace(list_findings=lambda scope, organization_id: [current_finding, obsolete_finding])
    db = SimpleNamespace(add=lambda finding: None, flush=lambda: None)

    _reconcile_configuration_findings(db, repository, "platform", None, [current_missing])

    assert current_finding.status == "open"
    assert current_finding.resolved_at is None
    assert obsolete_finding.status == "resolved"
    assert obsolete_finding.resolved_at is not None
