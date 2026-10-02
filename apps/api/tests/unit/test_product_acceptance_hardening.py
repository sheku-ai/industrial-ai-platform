from __future__ import annotations

import uuid
from typing import Any

from app.services.product_acceptance.gateway import HttpResult
from app.services.product_acceptance.runtime import LocalProductAcceptanceRuntime, RuntimeOptions


class HierarchyHttp:
    def __init__(self, organization_id: str, *, create_status: int = 200, persist_created: bool = True) -> None:
        self.organization_id = organization_id
        self.create_status = create_status
        self.persist_created = persist_created
        self.nodes: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []

    def get(self, path: str, query: dict[str, Any] | None = None) -> HttpResult:
        del query
        data: Any
        if path == "/core/organizations":
            data = [{"id": self.organization_id}]
        elif path == "/core/organization-nodes":
            data = self.nodes
        elif path == "/core/organization-relationships":
            data = self.relationships
        else:
            data = []
        return HttpResult(True, 200, "GET", path, data=data)

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> HttpResult:
        del idempotency_key
        if self.create_status != 200:
            return HttpResult(False, self.create_status, "POST", path, data={"detail": "forbidden"})
        item = {**(payload or {}), "id": str(uuid.uuid4())}
        if self.persist_created:
            if path == "/core/organization-nodes":
                self.nodes.append(item)
            elif path == "/core/organization-relationships":
                self.relationships.append(item)
        return HttpResult(True, 200, "POST", path, data=item)


def _runtime(http: HierarchyHttp) -> LocalProductAcceptanceRuntime:
    runtime = LocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://acceptance.invalid/api"))
    runtime.http = http
    runtime.state.resources["organization"] = {"id": http.organization_id}
    return runtime


def _hierarchy_gate(runtime: LocalProductAcceptanceRuntime) -> dict[str, Any]:
    return next(gate for gate in runtime.state.gates if gate["gate_code"] == "organization_hierarchy")


def test_hierarchy_creation_forbidden_cannot_pass_gate() -> None:
    runtime = _runtime(HierarchyHttp(str(uuid.uuid4()), create_status=403))

    runtime._organization("organization")

    assert _hierarchy_gate(runtime)["status"] == "FAILED"


def test_three_nodes_and_two_relationships_persisted_pass_gate() -> None:
    runtime = _runtime(HierarchyHttp(str(uuid.uuid4())))

    runtime._organization("organization")

    gate = _hierarchy_gate(runtime)
    assert gate["status"] == "PASSED"
    assert gate["details"]["node_count"] == 3
    assert gate["details"]["relationship_count"] == 2
    assert gate["details"]["evidence_origin"] == "public_api_read_after_write"


def test_historical_hierarchy_cannot_satisfy_current_execution() -> None:
    http = HierarchyHttp(str(uuid.uuid4()), persist_created=False)
    http.nodes = [
        {"id": str(uuid.uuid4()), "organization_id": http.organization_id, "code": "historical-root"}
        for _ in range(3)
    ]
    http.relationships = [
        {"id": str(uuid.uuid4()), "organization_id": http.organization_id, "relationship_type": "contains"}
        for _ in range(2)
    ]
    runtime = _runtime(http)

    runtime._organization("organization")

    gate = _hierarchy_gate(runtime)
    assert gate["status"] == "FAILED"
    assert gate["details"]["node_count"] == 0
    assert gate["details"]["relationship_count"] == 0
