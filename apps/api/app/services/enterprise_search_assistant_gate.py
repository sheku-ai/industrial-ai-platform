from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.enterprise_search import EnterpriseSearchEvidenceV1
from app.services.enterprise_search_evidence_reader import read_enterprise_search_evidence_v1
from app.services.enterprise_search_session import normalize_query_text

ENTERPRISE_SEARCH_ASSISTANT_GATE_VERSION = "v1"


@dataclass(frozen=True)
class EnterpriseSearchAssistantGateV1:
    organization_id: uuid.UUID
    evidence_id: uuid.UUID
    enterprise_search_evidence: EnterpriseSearchEvidenceV1 | None
    ready: bool
    blocking_issues: tuple[dict[str, Any], ...]
    gate_version: str = ENTERPRISE_SEARCH_ASSISTANT_GATE_VERSION


def _issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "enterprise_search_evidence",
        "item_id": None,
        "message": message,
    }


def evaluate_enterprise_search_assistant_gate_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
    expected_query: str,
) -> EnterpriseSearchAssistantGateV1:
    """Authorize Assistant Search consumption from persisted Enterprise Search evidence."""

    evidence = read_enterprise_search_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )
    if evidence is None:
        return EnterpriseSearchAssistantGateV1(
            organization_id=organization_id,
            evidence_id=evidence_id,
            enterprise_search_evidence=None,
            ready=False,
            blocking_issues=(
                _issue(
                    "enterprise_search_evidence_missing",
                    "Assistant execution requires persisted Enterprise Search evidence.",
                ),
            ),
        )

    blocking_issues: list[dict[str, Any]] = []
    if evidence.search_status != "completed":
        blocking_issues.append(
            _issue(
                "enterprise_search_not_completed",
                "Assistant execution requires Enterprise Search status=completed.",
            )
        )
    if evidence.persistence_status != "persisted":
        blocking_issues.append(
            _issue(
                "enterprise_search_not_persisted",
                "Assistant execution requires Enterprise Search evidence persisted in PostgreSQL.",
            )
        )
    if not evidence.search_uses_postgresql or not evidence.search_uses_postgresql_fts:
        blocking_issues.append(
            _issue(
                "enterprise_search_postgresql_fts_missing",
                "Assistant execution requires persisted PostgreSQL FTS search evidence.",
            )
        )
    if evidence.semantic_search_used or evidence.embeddings_required or evidence.ai_required:
        blocking_issues.append(
            _issue(
                "enterprise_search_ai_dependency_invalid",
                "Assistant execution baseline search evidence must not require semantic search, embeddings, or AI.",
            )
        )
    if evidence.normalized_query != normalize_query_text(expected_query):
        blocking_issues.append(
            _issue(
                "enterprise_search_query_mismatch",
                "Persisted Enterprise Search evidence does not match the Assistant requested query.",
            )
        )

    return EnterpriseSearchAssistantGateV1(
        organization_id=organization_id,
        evidence_id=evidence_id,
        enterprise_search_evidence=evidence,
        ready=not blocking_issues,
        blocking_issues=tuple(blocking_issues),
    )


def serialize_enterprise_search_assistant_gate_v1(
    gate: EnterpriseSearchAssistantGateV1,
) -> dict[str, Any]:
    evidence = gate.enterprise_search_evidence
    return {
        "gate_version": gate.gate_version,
        "organization_id": str(gate.organization_id),
        "enterprise_search_evidence_id": str(gate.evidence_id),
        "search_session_id": evidence.search_session_id if evidence is not None else None,
        "search_status": evidence.search_status if evidence is not None else None,
        "normalized_query": evidence.normalized_query if evidence is not None else None,
        "result_count": evidence.result_count if evidence is not None else None,
        "search_uses_postgresql": evidence.search_uses_postgresql if evidence is not None else None,
        "search_uses_postgresql_fts": evidence.search_uses_postgresql_fts if evidence is not None else None,
        "persistence_status": evidence.persistence_status if evidence is not None else None,
        "ready": gate.ready,
        "blocking_issues": [dict(item) for item in gate.blocking_issues],
        "authority": "postgresql",
        "contract": "EnterpriseSearchEvidenceV1",
    }
