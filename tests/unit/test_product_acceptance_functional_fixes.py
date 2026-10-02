from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.services.product_acceptance.contracts import AcceptanceIdentity
from app.services.product_acceptance.gateway import AcceptanceHttpClient, HttpResult
from app.services.product_acceptance.persistence import AcceptanceEvidenceClient
from app.services.product_acceptance.runtime import (
    ACCEPTANCE_SEARCH_QUERY,
    LocalProductAcceptanceRuntime,
    RuntimeOptions,
)


def _identity() -> AcceptanceIdentity:
    execution_id = "11111111-1111-4111-8111-111111111111"
    return AcceptanceIdentity(
        execution_id=execution_id,
        execution_key=f"local-product-acceptance-{execution_id}",
        correlation_id=f"correlation-{execution_id}",
        organization_external_ref=f"organization:{execution_id}",
        document_external_ref=f"document:{execution_id}",
        collection_external_ref=f"collection:{execution_id}",
        assistant_external_ref=f"assistant:{execution_id}",
        short_id=execution_id[:8],
    )


def test_evidence_writes_use_platform_scope_and_restore_organization_scope() -> None:
    identity = _identity()
    http = AcceptanceHttpClient("http://127.0.0.1:8000/api", identity.correlation_id)
    organization_id = "22222222-2222-4222-8222-222222222222"
    http.set_organization_scope(organization_id)
    observed_scopes: list[tuple[str | None, str | None]] = []

    def post(path: str, payload: dict[str, object] | None = None, **_: object) -> HttpResult:
        observed_scopes.append((http.authorization_scope, http.organization_id))
        return HttpResult(True, 201, "POST", path, data=payload or {})

    http.post = post  # type: ignore[method-assign]
    evidence = AcceptanceEvidenceClient(http, identity)
    evidence.available = True

    assert evidence.resource({"resource_type": "organization", "resource_id": organization_id})
    assert observed_scopes == [("platform", None)]
    assert http.authorization_scope == "organization"
    assert http.organization_id == organization_id


def test_organization_phase_uses_governed_structure_transaction() -> None:
    runtime = LocalProductAcceptanceRuntime(
        RuntimeOptions(api_base_url="http://127.0.0.1:8000/api", execution_key=_identity().execution_key)
    )
    organization_id = "22222222-2222-4222-8222-222222222222"
    runtime.state.resources["organization"] = {"id": organization_id}
    root_id = "33333333-3333-4333-8333-333333333333"
    unit_id = "44444444-4444-4444-8444-444444444444"
    team_id = "55555555-5555-4555-8555-555555555555"
    expected_codes = {
        f"root-{runtime.identity.short_id}": root_id,
        f"unit-{runtime.identity.short_id}": unit_id,
        f"team-{runtime.identity.short_id}": team_id,
    }

    http = MagicMock()
    http.get.return_value = HttpResult(
        True,
        200,
        "GET",
        "/core/organization-structure/runtime",
        data={
            "revision": 0,
            "nodes": [],
            "hierarchy": [],
            "node_type_catalog": [
                {
                    "code": "site",
                    "status": "active",
                    "available_for_new": True,
                    "allows_children": True,
                    "allowed_child_types": ["area"],
                    "display_order": 10,
                },
                {
                    "code": "area",
                    "status": "active",
                    "available_for_new": True,
                    "allows_children": True,
                    "allowed_child_types": ["team"],
                    "display_order": 20,
                },
                {
                    "code": "team",
                    "status": "active",
                    "available_for_new": True,
                    "allows_children": False,
                    "allowed_child_types": [],
                    "display_order": 30,
                },
            ],
        },
    )

    def put(path: str, payload: dict[str, object]) -> HttpResult:
        assert path == "/core/organization-structure/runtime"
        assert payload["expected_revision"] == 0
        assert uuid.UUID(str(payload["mutation_key"]))
        assert payload["normalize_legacy_contains"] is True
        proposals = payload["nodes"]
        assert isinstance(proposals, list)
        assert {item["code"] for item in proposals} == set(expected_codes)
        nodes = [
            {
                "id": node_id,
                "code": code,
                "node_type": proposal["node_type"],
                "name": proposal["name"],
                "metadata": proposal["metadata"],
                "position": proposal["position"],
                "status": "active",
            }
            for proposal in proposals
            for code, node_id in [(str(proposal["code"]), expected_codes[str(proposal["code"])])]
        ]
        return HttpResult(
            True,
            200,
            "PUT",
            path,
            data={
                "organization": {"id": organization_id},
                "revision": 1,
                "nodes": nodes,
                "hierarchy": [
                    {"parent_node_id": root_id, "child_node_id": unit_id},
                    {"parent_node_id": unit_id, "child_node_id": team_id},
                ],
            },
        )

    http.put.side_effect = put
    runtime.http = http
    runtime._organization("organization")

    gate = next(item for item in runtime.state.gates if item["gate_code"] == "organization_hierarchy")
    assert gate["status"] == "PASSED"
    assert gate["details"]["evidence_origin"] == "governed_organization_structure_read_after_write"
    http.get.assert_called_once_with("/core/organization-structure/runtime")
    http.put.assert_called_once()


def test_acceptance_search_query_is_deterministic_and_shared() -> None:
    runtime = LocalProductAcceptanceRuntime(
        RuntimeOptions(api_base_url="http://127.0.0.1:8000/api", execution_key=_identity().execution_key)
    )
    assert ACCEPTANCE_SEARCH_QUERY == "inspection"
    payload = runtime._document_lifecycle_payload("document_registration")
    assert payload["search_query"] == ACCEPTANCE_SEARCH_QUERY
    assert payload["registration"]["source_ref"] == {
        "provider": "product_acceptance",
        "reference": runtime.identity.document_external_ref,
    }
