from __future__ import annotations

import uuid

from app.models.production_acceptance import ProductionAcceptanceRun
from app.schemas.production_acceptance import ProductionBlocker
from app.services.configuration_preflight import is_placeholder_value, mask_setting_value
from app.services.production_acceptance_catalog import PRODUCTION_ACCEPTANCE_GATES
from app.services.production_acceptance_runtime import (
    _next_actions,
    calculate_domain_summaries,
    production_ready_from_gates,
    stable_hash,
)


class Gate:
    def __init__(self, gate_code: str, domain: str, status: str, mandatory: bool = True) -> None:
        self.gate_code = gate_code
        self.domain = domain
        self.status = status
        self.mandatory = mandatory
        self.summary = f"{gate_code} {status}"
        self.blocker_code = f"{gate_code}_blocked" if status in {"failed", "blocked"} else None
        self.warning_code = f"{gate_code}_warning" if status == "not_evaluated" else None


def test_production_ready_false_with_blocked_mandatory_gate() -> None:
    gates = [Gate("functional_gate", "functional", "passed"), Gate("recovery_gate", "recovery", "blocked")]

    assert production_ready_from_gates("blocked", gates, "a" * 64) is False


def test_production_ready_false_with_failed_mandatory_gate() -> None:
    gates = [Gate("functional_gate", "functional", "passed"), Gate("security_gate", "security", "failed")]

    assert production_ready_from_gates("failed", gates, "a" * 64) is False


def test_production_ready_true_only_when_all_mandatory_gates_pass() -> None:
    gates = [Gate("functional_gate", "functional", "passed"), Gate("security_gate", "security", "passed")]

    assert production_ready_from_gates("passed", gates, "a" * 64) is True
    assert production_ready_from_gates("running", gates, "a" * 64) is False
    assert production_ready_from_gates("passed", gates, None) is False


def test_domain_status_failed_precedence() -> None:
    summary = calculate_domain_summaries(
        [Gate("failed_gate", "security", "failed"), Gate("blocked_gate", "security", "blocked")]
    )["security"]

    assert summary.status == "failed"


def test_domain_status_blocked_precedence() -> None:
    summary = calculate_domain_summaries(
        [Gate("passed_gate", "operational", "passed"), Gate("blocked_gate", "operational", "blocked")]
    )["operational"]

    assert summary.status == "blocked"


def test_domain_status_not_evaluated() -> None:
    summary = calculate_domain_summaries([Gate("pending_gate", "capacity", "not_evaluated")])["capacity"]

    assert summary.status == "not_evaluated"


def test_domain_status_passed() -> None:
    summary = calculate_domain_summaries([Gate("one", "functional", "passed"), Gate("two", "functional", "passed")])[
        "functional"
    ]

    assert summary.status == "passed"


def test_evidence_hashing_is_deterministic() -> None:
    left = {"run_id": str(uuid.uuid4()), "payload": {"b": 2, "a": 1}}
    right = {"payload": {"a": 1, "b": 2}, "run_id": left["run_id"]}

    assert stable_hash(left) == stable_hash(right)


def test_configuration_placeholder_detection_and_masking() -> None:
    assert is_placeholder_value(" CHANGE-ME ")
    assert is_placeholder_value("secret")
    assert mask_setting_value("database_url", "postgresql://user:pass@example/db", sensitive=True) == "configured"
    assert mask_setting_value("object_storage_secret_key", "real-secret-value", sensitive=True) == "configured"
    assert mask_setting_value("application_version", "1.3.1") == "1.3.********"


def test_catalog_contains_required_domains_and_gates() -> None:
    domains = {gate.domain for gate in PRODUCTION_ACCEPTANCE_GATES}
    gate_codes = {gate.gate_code for gate in PRODUCTION_ACCEPTANCE_GATES}

    assert domains == {"functional", "operational", "security", "recovery", "deployment", "capacity", "portal"}
    assert "local_product_acceptance_passed" in gate_codes
    assert "backup_policy_configured" in gate_codes
    assert "portal_build_validated" in gate_codes


def test_idempotency_constraints_are_declared() -> None:
    names = {constraint.name for constraint in ProductionAcceptanceRun.__table__.constraints}
    index_names = {index.name for index in ProductionAcceptanceRun.__table__.indexes}

    assert "uq_runtime_production_acceptance_idempotency" in names
    assert "uq_runtime_production_acceptance_platform_idempotency" in index_names
    assert "uq_runtime_production_acceptance_org_idempotency" in index_names


def test_blocker_derived_next_actions() -> None:
    actions = _next_actions(
        [
            ProductionBlocker(
                code="BACKUP_POLICY_NOT_CONFIGURED",
                gate_code="backup_policy_configured",
                domain="recovery",
                message="Backup policy is missing.",
            )
        ]
    )

    assert actions[0]["action_key"] == "configure_backup_policy"
