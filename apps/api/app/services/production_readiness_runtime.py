from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.production_acceptance_runtime import build_current_product_state, get_latest_production_acceptance
from app.services.readiness_contract import READINESS_CONTRACT_VERSION

PRODUCTION_READINESS_RUNTIME_SCHEMA_VERSION = "3"
PRODUCTION_READINESS_RUNTIME_NAME = "production_readiness_runtime"


def _persisted_contracts(result: Any) -> dict[str, dict[str, Any]]:
    return {item.domain: item.model_dump(mode="json") for item in result.evidence_contracts}


def build_production_readiness_runtime(
    db: Session,
) -> dict[str, Any]:
    latest = get_latest_production_acceptance(db, scope="platform", organization_id=None)
    result = latest.result
    product_state = build_current_product_state(db, result, scope="platform", organization_id=None)
    if result is None:
        return {
            "production_readiness_runtime_schema_version": PRODUCTION_READINESS_RUNTIME_SCHEMA_VERSION,
            "runtime_name": PRODUCTION_READINESS_RUNTIME_NAME,
            "runtime_status": "not_evaluated",
            "status": product_state["release_eligibility"]["status"],
            "reason": product_state["release_eligibility"]["reason"],
            **product_state,
            "workspace_summary": {
                "production_candidate": False,
                "status": product_state["release_eligibility"]["status"],
            },
            "overall_production_readiness": {
                "production_candidate": False,
                "status": product_state["release_eligibility"]["status"],
                "blocking_reason_count": len(product_state["release_eligibility"]["blocking_reasons"]),
                "warning_count": 0,
            },
            "gate_matrix": [],
            "blockers": [],
            "warnings": [],
            "recommendations": [],
            "next_actions": [{"action": "run_production_acceptance"}],
            "production_score": {},
            "evidence_contracts": [],
            "evaluation_timestamp": None,
            "expires_at": None,
            "contract_version": READINESS_CONTRACT_VERSION,
            "runtime_version": "production-readiness-runtime.v3",
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        }

    contracts = _persisted_contracts(result)
    blockers = [item.model_dump(mode="json") for item in result.blockers]
    warnings = [item.model_dump(mode="json") for item in result.warnings]
    runtime_status = result.status
    domain_contracts = list(contracts.values())
    release_eligible = bool(product_state["release_eligibility"]["eligible"])
    return {
        "production_readiness_runtime_schema_version": PRODUCTION_READINESS_RUNTIME_SCHEMA_VERSION,
        "runtime_name": PRODUCTION_READINESS_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "status": product_state["release_eligibility"]["status"],
        "reason": product_state["release_eligibility"]["reason"],
        **product_state,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "status": product_state["release_eligibility"]["status"],
            "production_candidate": release_eligible,
            "acceptance_run_id": str(result.run_id),
            "contract_version": result.contract_version,
            "evaluation_timestamp": result.evaluated_at.isoformat(),
            "postgresql_source_of_truth": True,
        },
        "overall_production_readiness": {
            "production_candidate": release_eligible,
            "status": product_state["release_eligibility"]["status"],
            "product_acceptance_status": product_state["product_acceptance"]["status"],
            "evidence_freshness": product_state["evidence_freshness"]["status"],
            "blocking_reason_count": len(blockers),
            "warning_count": len(warnings),
            "evidence_contract_count": len(domain_contracts),
        },
        "gate_matrix": [item.model_dump(mode="json") for item in result.gate_results],
        "blockers": blockers,
        "warnings": warnings,
        "recommendations": result.recommendations,
        "next_actions": result.next_actions,
        "production_score": result.mandatory_gate_counts,
        "evidence_contracts": domain_contracts,
        "evaluation_timestamp": result.evaluation_timestamp,
        "expires_at": result.expires_at,
        "contract_version": READINESS_CONTRACT_VERSION,
        "runtime_version": "production-readiness-runtime.v3",
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
