from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.services.assistant_availability import (
    build_ai_capability_contract,
    evaluate_assistant_availability,
)
from app.services.data_classification import filter_visible_product_data, is_visible_product_data
from app.services.model_provider_center_runtime import _unique_by_persisted_identity
from app.services.product_integration_runtime import READY, _rc_gate
from app.services.product_state_contract import build_product_state_contract
from app.services.runtime_resolver import EXTRACTIVE, RuntimeResolution


def _acceptance_result(
    *,
    status: str,
    production_ready: bool,
    expires_at: datetime | None = None,
    mandatory_gate_counts: dict[str, int] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        reason=f"product_acceptance_{status}",
        production_ready=production_ready,
        mandatory_gate_counts=mandatory_gate_counts or {},
        evaluation_timestamp=datetime(2026, 7, 20, tzinfo=UTC),
        expires_at=expires_at,
    )


def _product_state(result: SimpleNamespace | None, *, now: datetime | None = None) -> dict[str, Any]:
    return build_product_state_contract(
        result,
        persisted_run_status=getattr(result, "status", None),
        evaluated_release_version="1.3.1",
        evidence_release_version="1.3.1" if result is not None else None,
        evidence_applicable=result is not None,
        release_evidence_expires_at=(now or datetime.now(UTC)) + timedelta(hours=1) if result is not None else None,
        now=now,
    )


def _runtime_resolution() -> RuntimeResolution:
    return RuntimeResolution(
        requested_answer_mode=EXTRACTIVE,
        resolved_answer_mode=EXTRACTIVE,
    )


def _assistant(
    organization_id: uuid.UUID,
    *,
    runtime_metadata: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        assistant_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="reference",
        assistant_status="active",
        default_search_mode="enterprise_search",
        runtime_metadata=runtime_metadata or {},
    )


def _source(organization_id: uuid.UUID, collection_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=organization_id,
        agent_id=None,
        collection_id=collection_id,
        config={"data_classification": "reference"},
        status="active",
    )


def test_domain_readiness_does_not_imply_release_eligibility() -> None:
    domain_readiness = {
        "required_domains": [{"domain": "documents", "status": READY, "ready": True, "blocking": False}],
        "optional_domains": [],
    }
    gate = _rc_gate(
        {"product_baseline_ready": True, "integration_ready": True, "blocking_issues": [], "warnings": []},
        domain_readiness,
        _product_state(_acceptance_result(status="blocked", production_ready=False)),
        side_effects_performed=False,
        external_calls_performed=False,
        llm_used=False,
        qdrant_used=False,
    )

    assert gate["domain_integration_ready"] is True
    assert gate["release_candidate_eligible"] is False
    assert gate["production_candidate"] is False


def test_blocked_product_acceptance_fails_release_eligibility_closed() -> None:
    state = _product_state(
        _acceptance_result(
            status="blocked",
            production_ready=False,
            mandatory_gate_counts={"blocked": 1},
        )
    )

    assert state["product_acceptance"]["status"] == "blocked"
    assert state["release_eligibility"]["eligible"] is False
    assert "mandatory_gate_blocked_or_failed" in state["release_eligibility"]["blocking_reasons"]


def test_blocked_product_acceptance_remains_distinct_from_expired_evidence() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)
    result = _acceptance_result(
        status="expired",
        production_ready=False,
        expires_at=now - timedelta(seconds=1),
    )
    result.functional_acceptance = SimpleNamespace(status="blocked")
    state = _product_state(result, now=now)

    assert state["product_acceptance"]["status"] == "blocked"
    assert state["product_acceptance"]["historical_result"] == "blocked"
    assert state["evidence_freshness"]["status"] == "expired"
    assert state["release_eligibility"]["eligible"] is False


def test_expired_acceptance_preserves_historical_result_but_is_not_eligible() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)
    result = _acceptance_result(
        status="passed",
        production_ready=True,
        expires_at=now - timedelta(seconds=1),
    )
    state = _product_state(result, now=now)

    assert state["product_acceptance"]["status"] == "expired"
    assert state["product_acceptance"]["historical_result"] == "passed"
    assert state["evidence_freshness"]["status"] == "expired"
    assert state["release_eligibility"]["eligible"] is False


def test_absent_product_acceptance_evidence_fails_closed() -> None:
    state = _product_state(None)

    assert state["product_acceptance"]["status"] == "unavailable"
    assert state["evidence_freshness"]["status"] == "unavailable"
    assert state["release_eligibility"]["eligible"] is False


def test_operational_configuration_scope_excludes_validation_and_legacy() -> None:
    records = [
        {"name": "Ordinary configuration", "config": {"data_classification": "validation"}},
        {"name": "Smoke words are not classification", "config": {"data_classification": "operational"}},
        {"name": "Reference configuration", "config": {"data_classification": "reference"}},
        {"name": "Legacy configuration", "config": {"data_origin": "legacy"}},
    ]
    visible = filter_visible_product_data(records, lambda item: (item["config"],))

    assert [item["name"] for item in visible] == [
        "Smoke words are not classification",
        "Reference configuration",
    ]
    assert len(visible) == sum(is_visible_product_data(item["config"]) for item in records)
    assert is_visible_product_data(records[3]["config"], include_validation=True) is False


def test_historical_llm_usage_does_not_enable_current_generative_capability() -> None:
    capabilities = build_ai_capability_contract(
        enterprise_search_available=True,
        assistant_availabilities=[],
        runtime_resolution=_runtime_resolution(),
        historical_llm_execution_count=7,
    )

    assert capabilities["deterministic_search"]["available"] is True
    assert capabilities["deterministic_search"]["requires_llm"] is False
    assert capabilities["generative_llm"]["provider_configured"] is False
    assert capabilities["generative_llm"]["model_configured"] is False
    assert capabilities["generative_llm"]["ready"] is False
    assert capabilities["historical_usage"]["historical_executions_exist"] is True
    assert capabilities["historical_usage"]["enables_current_configuration"] is False


def test_zero_assigned_sources_with_no_valid_alternate_scope_is_not_grounded() -> None:
    organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    assistant = _assistant(
        organization_id,
        runtime_metadata={"knowledge_source_ids": [str(uuid.uuid4())]},
    )
    availability = evaluate_assistant_availability(
        assistant,
        organization_sources=[_source(organization_id, collection_id)],
        searchable_collection_ids={collection_id},
        runtime_resolution=_runtime_resolution(),
        authorized=True,
    )

    assert availability["assigned_knowledge_source_count"] == 0
    assert availability["knowledge_scope_valid"] is False
    assert availability["grounded_answers_available"] is False


def test_assistant_knowledge_scope_preserves_organization_isolation() -> None:
    assistant_organization_id = uuid.uuid4()
    other_organization_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    availability = evaluate_assistant_availability(
        _assistant(assistant_organization_id),
        organization_sources=[_source(other_organization_id, collection_id)],
        searchable_collection_ids={collection_id},
        runtime_resolution=_runtime_resolution(),
        authorized=True,
    )

    assert availability["available_organization_source_count"] == 0
    assert availability["enterprise_search_available"] is False
    assert availability["grounded_answers_available"] is False


def test_duplicate_assistants_consolidate_only_by_persisted_identity_and_scope() -> None:
    organization_id = uuid.uuid4()
    repeated_id = uuid.uuid4()
    other_id = uuid.uuid4()
    records = [
        {
            "assistant_id": repeated_id,
            "assistant_name": "Reference Assistant",
            "ownership_scope": "organization",
            "organization_id": organization_id,
        },
        {
            "assistant_id": repeated_id,
            "assistant_name": "Reference Assistant",
            "ownership_scope": "organization",
            "organization_id": organization_id,
        },
        {
            "assistant_id": other_id,
            "assistant_name": "Reference Assistant",
            "ownership_scope": "organization",
            "organization_id": organization_id,
        },
    ]

    unique = _unique_by_persisted_identity(records, "assistant_id")

    assert [item["assistant_id"] for item in unique] == [repeated_id, other_id]
