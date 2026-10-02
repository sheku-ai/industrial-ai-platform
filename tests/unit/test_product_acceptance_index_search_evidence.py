from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.evidence_runtime import (  # noqa: E402
    EvidenceAwareLocalProductAcceptanceRuntime,
    _runtime_persistence_evidence_id,
)
from app.services.product_acceptance.gateway import HttpResult  # noqa: E402
from app.services.product_acceptance.runtime import RuntimeOptions  # noqa: E402

ORG_ID = "11111111-1111-1111-1111-111111111111"
ARTIFACT_ID = "22222222-2222-2222-2222-222222222222"
DOCUMENT_ID = "33333333-3333-3333-3333-333333333333"
VERSION_ID = "44444444-4444-4444-4444-444444444444"
KNOWLEDGE_DOCUMENT_ID = "55555555-5555-5555-5555-555555555555"
SEARCH_EVIDENCE_ID = "66666666-6666-6666-6666-666666666666"


def _runtime() -> EvidenceAwareLocalProductAcceptanceRuntime:
    runtime = EvidenceAwareLocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))
    runtime.state.resources.update(
        {
            "organization": {"id": ORG_ID},
            "artifact": {"id": ARTIFACT_ID},
            "document_record": {"id": DOCUMENT_ID},
            "document_version": {"id": VERSION_ID},
            "document_lifecycle": {
                "artifact_id": ARTIFACT_ID,
                "document_record_id": DOCUMENT_ID,
                "document_version_id": VERSION_ID,
                "knowledge_indexed": True,
                "knowledge_records": 2,
                "enterprise_search_visible": True,
            },
        }
    )
    return runtime


def _document_evidence(*, index_ready: bool = True) -> dict:
    return {
        "runtime_evidence_schema_version": "1",
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "artifact_id": ARTIFACT_ID,
        "document_record_id": DOCUMENT_ID,
        "document_version_id": VERSION_ID,
        "knowledge_index": {
            "authority": "postgresql",
            "contract": "KnowledgeIndexEvidenceV1",
            "knowledge_document_id": KNOWLEDGE_DOCUMENT_ID if index_ready else None,
            "ready": index_ready,
            "blocking_issues": [] if index_ready else [{"code": "knowledge_index_evidence_missing"}],
            "evidence": (
                {
                    "contract": "KnowledgeIndexEvidenceV1",
                    "knowledge_document_id": KNOWLEDGE_DOCUMENT_ID,
                    "organization_id": ORG_ID,
                    "artifact_id": ARTIFACT_ID,
                    "document_record_id": DOCUMENT_ID,
                    "document_version_id": VERSION_ID,
                    "status": "indexed",
                    "index_version": 1,
                }
                if index_ready
                else None
            ),
        },
    }


def _search_response(*, with_persisted_evidence: bool = True) -> dict:
    persistence = {
        "persistence_status": "completed",
        "persisted_records": (
            [
                {
                    "id": SEARCH_EVIDENCE_ID,
                    "runtime_domain": "enterprise_search",
                    "record_type": "search_result_set",
                    "persistence_status": "persisted",
                }
            ]
            if with_persisted_evidence
            else []
        ),
    }
    return {
        "search_status": "completed",
        "query": "inspection",
        "organization_id": ORG_ID,
        "result_count": 1,
        "results": [
            {
                "artifact_id": ARTIFACT_ID,
                "knowledge_document_id": KNOWLEDGE_DOCUMENT_ID,
            }
        ],
        "runtime_persistence": persistence,
    }


def _persisted_search_evidence() -> dict:
    return {
        "runtime_evidence_schema_version": "1",
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "evidence_id": SEARCH_EVIDENCE_ID,
        "expected_query": "inspection",
        "expected_artifact_id": ARTIFACT_ID,
        "expected_knowledge_document_id": KNOWLEDGE_DOCUMENT_ID,
        "result_artifact_ids": [ARTIFACT_ID],
        "result_knowledge_document_ids": [KNOWLEDGE_DOCUMENT_ID],
        "ready": True,
        "blocking_issues": [],
        "evidence": {
            "contract": "EnterpriseSearchEvidenceV1",
            "evidence_id": SEARCH_EVIDENCE_ID,
            "organization_id": ORG_ID,
            "query": "inspection",
            "normalized_query": "inspection",
            "search_status": "completed",
            "result_count": 1,
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
            "semantic_search_used": False,
            "embeddings_required": False,
            "ai_required": False,
            "persistence_status": "persisted",
        },
    }


def _http_result(path: str, data: dict, *, method: str = "GET") -> HttpResult:
    return HttpResult(ok=True, status_code=200, method=method, path=path, data=data)


def test_knowledge_index_legacy_true_without_authoritative_evidence_fails() -> None:
    runtime = _runtime()
    runtime.http.get = MagicMock(
        return_value=_http_result(
            "/product-acceptance/runtime-evidence/document-lifecycle",
            _document_evidence(index_ready=False),
        )
    )

    runtime._knowledge_index("knowledge_index")

    gate = runtime.state.gates[-1]
    assert gate["gate_code"] == "knowledge_index_ready"
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "KNOWLEDGE_INDEX_NOT_COMPLETED"
    assert gate["details"]["legacy_lifecycle_signal"]["value"] is True
    assert gate["details"]["legacy_lifecycle_signal"]["authoritative"] is False


def test_knowledge_index_requires_scoped_knowledge_index_evidence_v1() -> None:
    runtime = _runtime()
    runtime.http.get = MagicMock(
        return_value=_http_result(
            "/product-acceptance/runtime-evidence/document-lifecycle",
            _document_evidence(),
        )
    )

    runtime._knowledge_index("knowledge_index")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "PASSED"
    assert gate["details"]["authority"] == "postgresql"
    assert gate["details"]["contract_matches"] is True
    assert gate["details"]["evidence"]["evidence"]["contract"] == "KnowledgeIndexEvidenceV1"


def test_enterprise_search_http_success_without_persisted_evidence_fails() -> None:
    runtime = _runtime()
    runtime.http.get = MagicMock(
        return_value=_http_result(
            "/product-acceptance/runtime-evidence/document-lifecycle",
            _document_evidence(),
        )
    )
    runtime.http.post = MagicMock(
        return_value=_http_result(
            "/enterprise-search/search",
            _search_response(with_persisted_evidence=False),
            method="POST",
        )
    )

    runtime._enterprise_search("enterprise_search")

    gate = runtime.state.gates[-1]
    assert gate["gate_code"] == "enterprise_search_query"
    assert gate["status"] == "FAILED"
    assert gate["details"]["functional_search_succeeded"] is True
    assert gate["details"]["evidence_id"] is None
    assert gate["details"]["legacy_functional_result_authoritative"] is False


def test_enterprise_search_requires_exact_persisted_enterprise_search_evidence_v1() -> None:
    runtime = _runtime()
    runtime.http.get = MagicMock(
        side_effect=[
            _http_result(
                "/product-acceptance/runtime-evidence/document-lifecycle",
                _document_evidence(),
            ),
            _http_result(
                "/product-acceptance/runtime-evidence/enterprise-search",
                _persisted_search_evidence(),
            ),
        ]
    )
    runtime.http.post = MagicMock(
        return_value=_http_result(
            "/enterprise-search/search",
            _search_response(),
            method="POST",
        )
    )

    runtime._enterprise_search("enterprise_search")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "PASSED"
    assert gate["details"]["evidence_id"] == SEARCH_EVIDENCE_ID
    assert gate["details"]["contract_matches"] is True
    persisted = gate["details"]["persisted_evidence"]
    assert persisted["evidence"]["contract"] == "EnterpriseSearchEvidenceV1"
    search_payload = runtime.http.post.call_args.args[1]
    assert search_payload["artifact_id"] == ARTIFACT_ID
    assert search_payload["knowledge_document_id"] == KNOWLEDGE_DOCUMENT_ID


def test_runtime_persistence_evidence_id_ignores_wrong_record_type() -> None:
    payload = _search_response()
    payload["runtime_persistence"]["persisted_records"].insert(
        0,
        {
            "id": "77777777-7777-7777-7777-777777777777",
            "runtime_domain": "knowledge_fts",
            "record_type": "search_result_set",
            "persistence_status": "persisted",
        },
    )

    evidence_id = _runtime_persistence_evidence_id(
        payload,
        runtime_domain="enterprise_search",
        record_type="search_result_set",
    )

    assert evidence_id == SEARCH_EVIDENCE_ID
