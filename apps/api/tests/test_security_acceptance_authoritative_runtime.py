from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.services import security_acceptance_authoritative_runtime as runtime


def _check(code: str, status: str = "passed") -> SimpleNamespace:
    return SimpleNamespace(
        setting_code=code,
        status=status,
        masked_value="configured",
        reason="configured" if status == "passed" else "missing",
        mandatory=True,
        configured=status == "passed",
        placeholder=False,
        evidence_origin="configuration_preflight.get_settings",
        evaluated_at=datetime.now(UTC),
    )


def test_security_configuration_includes_identity_and_secure_cookie(monkeypatch) -> None:
    checks = [
        _check("authentication"),
        _check("identity_database_url"),
        _check("authentication_cookie_secure"),
    ]
    monkeypatch.setattr(runtime, "build_configuration_evidence_contract", lambda: checks)

    result = runtime.scan_security_configuration()

    assert [item.setting_code for item in result] == [
        "authentication",
        "identity_database_url",
        "authentication_cookie_secure",
    ]
    assert all(item.category == "authentication" for item in result)


def test_authentication_evidence_requires_all_authoritative_configuration(monkeypatch) -> None:
    checks = [
        _check("authentication"),
        _check("identity_database_url"),
        _check("authentication_cookie_secure", "blocked"),
    ]
    monkeypatch.setattr(runtime, "build_configuration_evidence_contract", lambda: checks)

    status, payload = runtime._authentication_configuration_evidence()

    assert status == "blocked"
    assert payload["required_checks"]["authentication_cookie_secure"]["status"] == "blocked"
    assert payload["authority"] == "configuration_preflight.get_settings"


def test_isolation_evidence_blocks_without_persisted_negative_acceptance_gate(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_latest_negative_isolation_gate", lambda *_args: None)

    status, payload, source_id = runtime._organization_isolation_evidence(
        SimpleNamespace(),
        "platform",
        None,
    )

    assert status == "blocked"
    assert payload["gate_code"] == "negative_org_isolation"
    assert payload["reason"] == "persisted_product_acceptance_gate_missing"
    assert source_id is None


def test_isolation_evidence_uses_persisted_product_acceptance_gate(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    gate_id = uuid.uuid4()
    completed_at = datetime.now(UTC)
    gate = SimpleNamespace(
        id=gate_id,
        gate_code="negative_org_isolation",
        status="PASSED",
        completed_at=completed_at,
        details={"cross_organization_access": "blocked"},
    )
    execution = SimpleNamespace(
        id=execution_id,
        execution_key="acceptance-1",
        status="PASSED",
        scenario="local-product-acceptance/v2",
        organization_id=organization_id,
    )
    monkeypatch.setattr(
        runtime,
        "_latest_negative_isolation_gate",
        lambda *_args: (gate, execution),
    )

    status, payload, source_id = runtime._organization_isolation_evidence(
        SimpleNamespace(),
        "organization",
        organization_id,
    )

    assert status == "passed"
    assert payload["gate_id"] == str(gate_id)
    assert payload["execution_id"] == str(execution_id)
    assert payload["authority"] == "runtime.acceptance_gates"
    assert source_id == str(gate_id)
