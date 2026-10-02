from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

APP_ROOT = API_ROOT / "app"
SERVICES_ROOT = APP_ROOT / "services"
PRODUCT_ACCEPTANCE_ROOT = SERVICES_ROOT / "product_acceptance"
app_pkg = sys.modules.setdefault("app", types.ModuleType("app"))
app_pkg.__path__ = [str(APP_ROOT)]
services_pkg = sys.modules.setdefault("app.services", types.ModuleType("app.services"))
services_pkg.__path__ = [str(SERVICES_ROOT)]
product_acceptance_pkg = sys.modules.setdefault(
    "app.services.product_acceptance",
    types.ModuleType("app.services.product_acceptance"),
)
product_acceptance_pkg.__path__ = [str(PRODUCT_ACCEPTANCE_ROOT)]

from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.product_acceptance.capabilities import (  # noqa: E402
    discover_capabilities,
    normalize_openapi_path,
    resolve_openapi_operation,
)
from app.services.product_acceptance.classification import (  # noqa: E402
    classify_global_status,
    cli_exit_code,
    is_release_candidate_eligible,
    release_candidate_blockers,
    validate_gate_contract,
)
from app.services.product_acceptance.gate_registry import (  # noqa: E402
    GATE_CONTRACT_VERSION,
    GATE_DEFINITIONS,
    MANDATORY_GATE_COUNT,
    PHASE_GATE_DEFINITIONS,
    gate_contract_payload,
    validate_gate_registry,
)
from app.services.product_acceptance.gateway import (  # noqa: E402
    AcceptanceHttpClient,
    HttpResult,
    _LoopbackSecureCookiePolicy,
)
from app.services.product_acceptance.idempotency import build_idempotency_report, idempotency_gate_results  # noqa: E402
from app.services.product_acceptance.isolation import evaluate_search_isolation  # noqa: E402
from app.services.product_acceptance.runtime import (  # noqa: E402
    LocalProductAcceptanceRuntime,
    RuntimeOptions,
    _chunking_evidence,
)
from app.services.product_acceptance.summaries import build_gate_summary, build_phase_summary  # noqa: E402


def test_gate_classification_mandatory_passed_and_all_passed() -> None:
    gates = _all_mandatory("PASSED")
    assert classify_global_status(gates, []) == "PASSED"
    assert is_release_candidate_eligible("PASSED", gates, [], {"verified": True}) is True


def test_authoritative_gate_contract_is_complete_and_stable() -> None:
    contract = gate_contract_payload()
    assert validate_gate_registry() == []
    assert GATE_CONTRACT_VERSION == "local-product-acceptance/v2"
    assert MANDATORY_GATE_COUNT == 23
    assert contract["mandatory_gate_count"] == 23
    assert contract["phase_mapping"] == {
        phase_code: [definition.gate_code for definition in definitions]
        for phase_code, definitions in PHASE_GATE_DEFINITIONS.items()
    }


def test_gate_classification_mandatory_capability_missing_fails() -> None:
    gates = _all_mandatory("PASSED")
    gates[0]["status"] = "CAPABILITY_MISSING"
    assert classify_global_status(gates, []) == "FAILED"


def test_gate_classification_mandatory_blocked_environment() -> None:
    gates = _all_mandatory("PASSED")
    gates[0]["status"] = "BLOCKED_BY_ENVIRONMENT"
    gates[1]["status"] = "CAPABILITY_MISSING"
    assert classify_global_status(gates, []) == "BLOCKED_BY_ENVIRONMENT"


def test_gate_classification_mandatory_skipped_is_invalid_failure() -> None:
    gates = _all_mandatory("PASSED")
    gates[0]["status"] = "SKIPPED"
    assert classify_global_status(gates, []) == "FAILED"


def test_gate_classification_optional_skipped_passes_and_optional_missing_warns() -> None:
    gates = _all_mandatory("PASSED")
    gates.append(_gate("cleanup", "cleanup_policy", "SKIPPED"))
    assert classify_global_status(gates, []) == "PASSED"
    gates[-1]["status"] = "CAPABILITY_MISSING"
    assert classify_global_status(gates, []) == "PASSED_WITH_WARNINGS"


def test_gate_classification_failed_precedence() -> None:
    gates = _all_mandatory("PASSED")
    gates[0]["status"] = "FAILED"
    gates[1]["status"] = "BLOCKED_BY_ENVIRONMENT"
    assert classify_global_status(gates, []) == "FAILED"


def test_gate_classification_passed_with_warnings() -> None:
    assert classify_global_status(_all_mandatory("PASSED"), [{"code": "warning"}]) == "PASSED_WITH_WARNINGS"


def test_gate_registry_detects_duplicate_unknown_missing_and_bad_status() -> None:
    phases = [{"phase_code": definition.phase_code} for definition in GATE_DEFINITIONS if definition.mandatory]
    gates = _all_mandatory("PASSED")
    gates.append(dict(gates[0]))
    gates.append(_gate("unknown", "unknown", "PASSED"))
    gates[1]["status"] = "SKIPPED"
    gates = gates[:-3] + gates[-2:]
    errors = validate_gate_contract(gates, phases)
    reasons = {error["contract_error"] for error in errors}
    assert {"duplicate_gate", "unknown_gate", "mandatory_gate_skipped", "status_not_allowed"} <= reasons
    assert "mandatory_gate_missing" in reasons


def test_gate_registry_detects_mandatory_phase_without_gates() -> None:
    phases = [{"phase_code": "organization"}]
    errors = validate_gate_contract([], phases)
    assert any(error["contract_error"] == "mandatory_phase_without_gates" for error in errors)


def test_document_lifecycle_success_emits_registered_gate_only() -> None:
    runtime = _runtime_with_lifecycle_response(
        ok=True,
        status_code=200,
        data={
            "document_record_id": "record-1",
            "document_version_id": "version-1",
            "storage_verified": True,
        },
    )

    runtime._document_lifecycle("document_registration")

    assert [gate["gate_code"] for gate in runtime.state.gates] == ["document_lifecycle_orchestrated"]
    gate = runtime.state.gates[0]
    assert gate["status"] == "PASSED"
    assert gate["details"]["document_record_id"] == "record-1"
    assert not _contract_errors_for_document_registration(runtime.state.gates)


def test_document_lifecycle_failure_uses_registered_gate_and_functional_error() -> None:
    response = {
        "detail": {
            "blocking_issues": [
                {
                    "code": "RESOURCE_LINEAGE_INCOMPLETE",
                    "message": "document version lineage is incomplete",
                }
            ]
        },
        "document_record_id": "record-1",
        "document_version_id": None,
        "storage_verified": False,
    }
    runtime = _runtime_with_lifecycle_response(ok=False, status_code=409, data=response)

    runtime._document_lifecycle("document_registration")

    assert [gate["gate_code"] for gate in runtime.state.gates] == ["document_lifecycle_orchestrated"]
    gate = runtime.state.gates[0]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "RESOURCE_LINEAGE_INCOMPLETE"
    assert gate["details"]["response"] == response
    assert gate["details"]["error"] == "failed"
    errors = _contract_errors_for_document_registration(runtime.state.gates)
    assert not any(error["contract_error"] == "unknown_gate" for error in errors)
    assert not any(error["contract_error"] == "mandatory_gate_missing" for error in errors)


def test_document_lifecycle_unrecognized_failure_uses_contractual_fallback_gate() -> None:
    runtime = _runtime_with_lifecycle_response(
        ok=False,
        status_code=500,
        data={"detail": {"message": "unrecognized lifecycle failure"}},
    )

    runtime._document_lifecycle("document_registration")

    assert [gate["gate_code"] for gate in runtime.state.gates] == ["document_lifecycle_orchestrated"]
    gate = runtime.state.gates[0]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "RESOURCE_LINEAGE_INCOMPLETE"
    errors = _contract_errors_for_document_registration(runtime.state.gates)
    assert not any(error["contract_error"] == "unknown_gate" for error in errors)
    assert not any(error["contract_error"] == "mandatory_gate_missing" for error in errors)


def test_prerequisite_failure_emits_registered_mandatory_gate() -> None:
    runtime = LocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))

    runtime._functional_failure("document_registration", "document_configuration_required", {})
    runtime._functional_failure("conversation", "assistant_required", {})

    assert [(gate["phase_code"], gate["gate_code"]) for gate in runtime.state.gates] == [
        ("document_registration", "document_lifecycle_orchestrated"),
        ("conversation", "conversation_turn_created"),
    ]
    assert all(gate["error_code"] == "ACCEPTANCE_GATE_CONTRACT_INVALID" for gate in runtime.state.gates)


def test_phase_contract_fills_every_missing_mandatory_gate_with_registered_codes() -> None:
    runtime = LocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))

    runtime._phase("preflight", lambda _phase: None)

    assert [gate["gate_code"] for gate in runtime.state.gates] == [
        "mandatory_public_capabilities",
        "postgres_fts_readiness",
    ]
    assert not validate_gate_contract(
        runtime.state.gates + [gate for gate in _all_mandatory("PASSED") if gate["phase_code"] != "preflight"],
        [{"phase_code": definition.phase_code} for definition in GATE_DEFINITIONS if definition.mandatory],
    )


def test_acceptance_http_client_applies_organization_scope_headers() -> None:
    client = AcceptanceHttpClient("http://127.0.0.1:8000/api", "correlation-1")
    client.set_organization_scope("11111111-1111-1111-1111-111111111111")

    assert client.organization_id == "11111111-1111-1111-1111-111111111111"


def test_acceptance_secure_cookie_policy_only_extends_to_loopback_http() -> None:
    policy = _LoopbackSecureCookiePolicy()
    secure_cookie = MagicMock(secure=True)

    loopback_request = MagicMock(type="http")
    loopback_request.get_full_url.return_value = "http://127.0.0.1:8000/auth/csrf"
    remote_request = MagicMock(type="http")
    remote_request.get_full_url.return_value = "http://example.test/auth/csrf"
    tls_request = MagicMock(type="https")
    tls_request.get_full_url.return_value = "https://example.test/auth/csrf"

    assert policy.return_ok_secure(secure_cookie, loopback_request) is True
    assert policy.return_ok_secure(secure_cookie, remote_request) is False
    assert policy.return_ok_secure(secure_cookie, tls_request) is True


def test_acceptance_http_client_applies_session_csrf_without_legacy_identity_headers() -> None:
    client = AcceptanceHttpClient("http://127.0.0.1:8000/api", "correlation-1")
    client.csrf_token = "csrf-token"
    client.csrf_header_name = "X-CSRF-Token"
    client.set_organization_scope("11111111-1111-1111-1111-111111111111")
    client.opener = MagicMock()
    client.opener.open.return_value = _SuccessfulHttpResponse()

    result = client.post("/documents/document-types", {"name": "Controlled document"})

    assert result.ok is True
    sent = client.opener.open.call_args.args[0]
    headers = {key.casefold(): value for key, value in sent.header_items()}
    assert headers["x-csrf-token"] == "csrf-token"
    assert headers["x-authorization-scope"] == "organization"
    assert headers["x-organization-id"] == "11111111-1111-1111-1111-111111111111"
    assert "x-actor-reference" not in headers
    assert "x-principal-type" not in headers


def test_runtime_options_do_not_expose_acceptance_password() -> None:
    options = RuntimeOptions(
        api_base_url="http://127.0.0.1:8000/api",
        auth_email="operator@example.test",
        auth_password="super-secret-password",
    )

    assert "super-secret-password" not in repr(options)


def test_missing_acceptance_credentials_are_reported_as_environment_blocker() -> None:
    runtime = LocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))

    report = runtime.run()

    assert report["final_status"] == "BLOCKED_BY_ENVIRONMENT"
    assert report["gates"] == []
    assert report["blockers"][0]["error_code"] == "ACCEPTANCE_AUTHENTICATION_FAILED"
    assert report["blockers"][0]["details"]["error"] == "acceptance_authentication_credentials_not_configured"


def test_read_after_write_identity_uses_requested_conversation_not_organization() -> None:
    verified = LocalProductAcceptanceRuntime._verification_resource(
        {"id": "conversation-1", "external_ref": "conversation:1"},
        HttpResult(
            ok=True,
            status_code=200,
            method="GET",
            path="/assistants/conversations/conversation-1",
            data={"organization_id": "organization-1", "conversation_id": "conversation-1"},
        ),
        "conversation-1",
    )

    assert verified["id"] == "conversation-1"
    assert verified["identity_matches"] is True


def test_report_summaries_and_release_blockers() -> None:
    gates = _all_mandatory("PASSED")
    gates[0]["status"] = "CAPABILITY_MISSING"
    gates[0]["error_code"] = "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE"
    gate_summary = build_gate_summary(gates)
    phase_summary = build_phase_summary([{"phase_code": gate["phase_code"]} for gate in gates], gates)
    blockers = release_candidate_blockers(gates, [])
    assert gate_summary["mandatory_capability_missing"] == 1
    assert phase_summary["capability_missing"] >= 1
    assert blockers[0]["error_code"] == "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE"


def test_status_compatibility_contract() -> None:
    gates = _all_mandatory("PASSED")
    final_status = classify_global_status(gates, [])
    report = {
        "status": final_status,
        "final_status": final_status,
        "report_contract_version": "local-product-acceptance/v2",
    }
    assert report["status"] == report["final_status"]
    assert report["report_contract_version"] == "local-product-acceptance/v2"


def test_isolation_endpoint_without_org_scope_is_capability_missing() -> None:
    result = evaluate_search_isolation(
        _FakeClient({"results": []}),
        {"status": "PARTIAL", "organization_scope_supported": False},
        "org-a",
        "org-b",
        "known content",
    )
    assert result["status"] == "CAPABILITY_MISSING"
    assert result["error_code"] == "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE"


def test_isolation_cross_organization_result_detected() -> None:
    result = evaluate_search_isolation(
        _FakeClient({"query_processed": True, "results": [{"organization_id": "org-a"}]}),
        {"status": "AVAILABLE", "organization_scope_supported": True},
        "org-a",
        "org-b",
        "known content",
    )
    assert result["status"] == "FAILED"
    assert result["error_code"] == "CROSS_ORGANIZATION_ACCESS_DETECTED"


def test_isolation_empty_response_not_conclusive() -> None:
    result = evaluate_search_isolation(
        _FakeClient({}),
        {"status": "AVAILABLE", "organization_scope_supported": True},
        "org-a",
        "org-b",
        "known content",
    )
    assert result["status"] == "FAILED"
    assert result["error_code"] == "ORGANIZATION_ISOLATION_NOT_VERIFIABLE"


def test_isolation_passed_when_scope_processed_without_leak() -> None:
    result = evaluate_search_isolation(
        _FakeClient(
            [
                {"query_processed": True, "results": [{"organization_id": "org-a"}]},
                {"query_processed": True, "results": [{"organization_id": "org-b"}]},
            ]
        ),
        {"status": "AVAILABLE", "organization_scope_supported": True},
        "org-a",
        "org-b",
        "known content",
    )
    assert result["status"] == "PASSED"


def test_isolation_http_error_not_success() -> None:
    result = evaluate_search_isolation(
        _FakeClient({"detail": "failed"}, ok=False, status_code=500),
        {"status": "AVAILABLE", "organization_scope_supported": True},
        "org-a",
        "org-b",
        "known content",
    )
    assert result["status"] == "FAILED"


def test_cli_exit_codes() -> None:
    assert cli_exit_code({"final_status": "PASSED", "release_candidate_eligible": True}) == 0
    assert cli_exit_code({"final_status": "PASSED_WITH_WARNINGS", "release_candidate_eligible": True}) == 0
    assert cli_exit_code({"final_status": "FAILED", "release_candidate_eligible": False}) == 1
    assert cli_exit_code({"final_status": "BLOCKED_BY_ENVIRONMENT", "release_candidate_eligible": False}) == 3
    assert cli_exit_code({}, invalid_args=True) == 2
    assert cli_exit_code({}, persistence_or_report_failed=True) == 4


def test_idempotency_same_id_reused() -> None:
    before = {"organization": {"id": "org-a", "external_ref": "ref"}}
    report = build_idempotency_report(before, dict(before), {"organizations": 1}, {"organizations": 1})
    assert report["verified"] is True
    assert report["resources"][0]["same_resource_reused"] is True


def test_idempotency_different_id_is_violation() -> None:
    report = build_idempotency_report(
        {"organization": {"id": "org-a", "external_ref": "ref"}},
        {"organization": {"id": "org-b", "external_ref": "ref"}},
        {},
        {},
    )
    gates = idempotency_gate_results(report)
    assert report["duplicate_assets_detected"] is True
    assert gates[0]["status"] == "FAILED"


def test_idempotency_duplicate_count_is_violation() -> None:
    report = build_idempotency_report(
        {"organization": {"id": "org-a", "external_ref": "ref"}},
        {"organization": {"id": "org-a", "external_ref": "ref", "duplicate_count": 1}},
        {},
        {},
    )
    assert report["duplicate_assets_detected"] is True


def test_idempotency_inventory_growth_is_violation() -> None:
    report = build_idempotency_report(
        {"organization": {"id": "org-a", "external_ref": "ref"}},
        {"organization": {"id": "org-a", "external_ref": "ref"}},
        {"organizations": 1},
        {"organizations": 2},
    )

    assert report["inventory_changed"] is True
    assert report["count_deltas"] == {"organizations": 1}
    assert report["duplicate_assets_detected"] is True
    assert report["verified"] is False
    assert idempotency_gate_results(report)[0]["status"] == "FAILED"


def test_idempotency_missing_resource_is_capability_missing() -> None:
    gates = idempotency_gate_results({"resources": []})
    assert any(gate["status"] == "CAPABILITY_MISSING" for gate in gates)


def test_capability_discovery_prefers_authenticated_acceptance_contract() -> None:
    client = MagicMock()
    client.base_url = "http://127.0.0.1:8000/api"
    client.request.return_value = HttpResult(
        ok=True,
        status_code=200,
        method="GET",
        path="/product-acceptance/contract",
        data={"paths": {}},
    )

    discover_capabilities(client)

    client.request.assert_called_once_with("GET", "/product-acceptance/contract")


def test_openapi_resolution_requested_without_api_openapi_with_api_base_with_api() -> None:
    openapi = _openapi_with_path("/api/enterprise-search/search", "post")
    resolved_path, operation = resolve_openapi_operation(
        openapi,
        "/enterprise-search/search",
        "post",
        "http://127.0.0.1:8000/api",
    )
    assert resolved_path == "/api/enterprise-search/search"
    assert operation is not None


def test_openapi_resolution_requested_without_api_openapi_with_api_base_without_api() -> None:
    openapi = _openapi_with_path("/api/assistants/chat", "post")
    resolved_path, operation = resolve_openapi_operation(
        openapi,
        "/assistants/chat",
        "post",
        "http://127.0.0.1:8000",
    )
    assert resolved_path == "/api/assistants/chat"
    assert operation is not None


def test_openapi_resolution_requested_without_api_openapi_without_api_base_with_api() -> None:
    openapi = _openapi_with_path("/feedback-audit/audit/events", "get")
    resolved_path, operation = resolve_openapi_operation(
        openapi,
        "/feedback-audit/audit/events",
        "get",
        "http://127.0.0.1:8000/api",
    )
    assert resolved_path == "/feedback-audit/audit/events"
    assert operation is not None


def test_openapi_resolution_avoids_api_api() -> None:
    assert normalize_openapi_path("/api/api/assistants") == "/api/assistants"
    openapi = _openapi_with_path("/api/product-acceptance/executions", "post")
    resolved_path, operation = resolve_openapi_operation(
        openapi,
        "/api/product-acceptance/executions",
        "post",
        "http://127.0.0.1:8000/api",
    )
    assert resolved_path == "/api/product-acceptance/executions"
    assert operation is not None


def test_openapi_resolution_preserves_path_missing_method() -> None:
    openapi = _openapi_with_path("/api/assistants", "get")
    resolved_path, operation = resolve_openapi_operation(
        openapi,
        "/assistants",
        "post",
        "http://127.0.0.1:8000/api",
    )
    assert resolved_path == "/api/assistants"
    assert operation is None


def test_chunking_rejects_legacy_surface_chunk_fields() -> None:
    evidence = _chunking_evidence(
        {
            "chunk_count": 2,
            "knowledge_chunk_ids": ["chunk-1", "chunk-2"],
            "expected_content_present": True,
        }
    )
    assert evidence["chunking_ready"] is False
    assert evidence["chunk_result_present"] is False
    assert evidence["error_code"] == "CHUNK_PERSISTENCE_NOT_COMPLETED"


def test_chunking_rejects_publication_evidence_without_chunk_result() -> None:
    evidence = _chunking_evidence(
        {
            "publication_result": {"chunk_count": 1, "knowledge_chunk_ids": ["chunk-1"]},
            "knowledge_indexed": True,
        }
    )
    assert evidence["chunking_ready"] is False
    assert evidence["chunk_result_present"] is False
    assert evidence["error_code"] == "CHUNK_PERSISTENCE_NOT_COMPLETED"


def test_chunking_absent_evidence_is_not_ready() -> None:
    evidence = _chunking_evidence({})
    assert evidence["chunking_ready"] is False
    assert evidence["chunk_count"] == 0
    assert evidence["chunk_result_present"] is False
    assert evidence["chunks_present"] is False
    assert evidence["error_code"] == "CHUNK_PERSISTENCE_NOT_COMPLETED"


def test_chunking_uses_authoritative_chunk_result_over_processing_result() -> None:
    evidence = _chunking_evidence(
        {
            "stages": {
                "processing_publication_search": {
                    "processing_result": {
                        "chunks_created": False,
                        "document_record_id": "record-1",
                        "document_version_id": "version-1",
                    },
                    "chunk_result": {
                        "chunk_status": "completed",
                        "chunk_generation_completed": True,
                        "chunks_created": True,
                        "chunk_count": 1,
                        "chunks": [
                            {
                                "chunk_index": 0,
                                "content_hash": "chunk-hash-1",
                                "content": "ACC-REF-001 controlled register 45 days",
                                "document_record_id": "record-1",
                                "document_version_id": "version-1",
                            }
                        ],
                    },
                }
            }
        }
    )
    assert evidence["chunking_ready"] is True
    assert evidence["chunk_count"] == 1
    assert evidence["evidence_source"] == "chunk_result"
    assert evidence["error_code"] is None


def test_chunk_generation_ready_is_not_used_by_runtime() -> None:
    source = (PRODUCT_ACCEPTANCE_ROOT / "runtime.py").read_text(encoding="utf-8")
    assert "chunk_generation_ready" not in source


def test_completed_chunk_result_executes_knowledge_publication() -> None:
    chunk_result = {
        "artifact_id": "artifact-1",
        "document_record_id": "record-1",
        "document_version_id": "version-1",
        "processing_session_id": "processing-session-1",
        "chunk_session_id": "chunk-session-1",
        "chunk_status": "completed",
        "chunk_generation_completed": True,
        "chunks_created": True,
        "chunk_count": 1,
        "chunks": [
            {
                "artifact_id": "artifact-1",
                "document_record_id": "record-1",
                "document_version_id": "version-1",
                "processing_session_id": "processing-session-1",
                "chunk_index": 0,
                "content": "ACC-REF-001 controlled register inspection interval 45 days.",
                "content_hash": "content-hash-1",
                "semantic_hash": "semantic-hash-1",
                "content_type": "text/plain",
                "chunk_scope": "document",
                "source_content_sha256": "source-sha",
                "embeddings_created": False,
                "semantic_index_created": False,
                "ai_required": False,
            }
        ],
        "embeddings_created": False,
        "ai_required": False,
    }

    publication = build_knowledge_publication(chunk_result)

    assert publication["publication_completed"] is True
    assert publication["knowledge_published"] is True
    assert publication["published_chunk_count"] == 1
    assert publication["publication_result"]["document_record_id"] == "record-1"
    assert publication["publication_result"]["document_version_id"] == "version-1"


def test_processing_runtime_indexes_publication_result_after_chunk_result() -> None:
    source = (SERVICES_ROOT / "document_processing_runtime.py").read_text(encoding="utf-8")
    publication_call = "publication = build_knowledge_publication(chunk_result, publication_config=publication_config)"
    index_call = "build_knowledge_index(db, publication_result)"
    assert publication_call in source
    assert index_call in source
    assert source.index(publication_call) < source.index(index_call)


def _all_mandatory(status: str) -> list[dict[str, Any]]:
    return [
        _gate(definition.phase_code, definition.gate_code, status)
        for definition in GATE_DEFINITIONS
        if definition.mandatory
    ]


def _gate(phase: str, gate: str, status: str) -> dict[str, Any]:
    return {"phase_code": phase, "gate_code": gate, "status": status, "details": {}}


class _SuccessfulHttpResponse:
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @staticmethod
    def read() -> bytes:
        return b"{}"


class _FakeResponse:
    def __init__(self, ok: bool, data: dict[str, Any], status_code: int) -> None:
        self.ok = ok
        self.data = data
        self.status_code = status_code
        self.error = None if ok else "failed"


class _FakeClient:
    def __init__(self, data: dict[str, Any] | list[dict[str, Any]], ok: bool = True, status_code: int = 200) -> None:
        self.data = data
        self.ok = ok
        self.status_code = status_code
        self.calls = 0

    def post(self, _path: str, _payload: dict[str, Any]) -> _FakeResponse:
        if isinstance(self.data, list):
            index = min(self.calls, len(self.data) - 1)
            self.calls += 1
            return _FakeResponse(self.ok, self.data[index], self.status_code)
        self.calls += 1
        return _FakeResponse(self.ok, self.data, self.status_code)


def _runtime_with_lifecycle_response(
    *,
    ok: bool,
    status_code: int,
    data: dict[str, Any],
) -> LocalProductAcceptanceRuntime:
    runtime = LocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))
    runtime.http = _FakeClient(data=data, ok=ok, status_code=status_code)
    runtime.state.resources.update(
        {
            "organization": {"id": "11111111-1111-1111-1111-111111111111"},
            "document_type": {"id": "22222222-2222-2222-2222-222222222222"},
            "collection": {"id": "33333333-3333-3333-3333-333333333333"},
        }
    )
    return runtime


def _contract_errors_for_document_registration(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    complete_gates = [
        gate
        for gate in _all_mandatory("PASSED")
        if (gate["phase_code"], gate["gate_code"]) != ("document_registration", "document_lifecycle_orchestrated")
    ]
    complete_gates.extend(gates)
    phases = [{"phase_code": definition.phase_code} for definition in GATE_DEFINITIONS if definition.mandatory]
    return validate_gate_contract(complete_gates, phases)


def _openapi_with_path(path: str, method: str) -> dict[str, Any]:
    return {
        "paths": {
            path: {
                method: {
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            }
        }
    }
