from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.isolation import evaluate_search_isolation  # noqa: E402


class _Response:
    def __init__(self, data: dict[str, Any]) -> None:
        self.ok = True
        self.status_code = 200
        self.data = data
        self.error = None


class _ScopeAwareClient:
    def __init__(self) -> None:
        self.authorization_scope = "organization"
        self.organization_id = "org-original"
        self.observed_scopes: list[str | None] = []
        self.responses = [
            _Response({"query_processed": True, "results": [{"organization_id": "org-a"}]}),
            _Response({"query_processed": True, "results": []}),
        ]

    def set_organization_scope(self, organization_id: str) -> None:
        self.authorization_scope = "organization"
        self.organization_id = organization_id

    def set_platform_scope(self) -> None:
        self.authorization_scope = "platform"
        self.organization_id = None

    def post(self, _path: str, payload: dict[str, Any]) -> _Response:
        self.observed_scopes.append(self.organization_id)
        assert payload["organization_id"] == self.organization_id
        return self.responses.pop(0)


def test_search_isolation_switches_scope_for_each_organization_and_restores_original_scope() -> None:
    client = _ScopeAwareClient()

    result = evaluate_search_isolation(
        client,
        {"status": "AVAILABLE", "organization_scope_supported": True},
        "org-a",
        "org-b",
        "inspection",
    )

    assert result["status"] == "PASSED"
    assert client.observed_scopes == ["org-a", "org-b"]
    assert client.authorization_scope == "organization"
    assert client.organization_id == "org-original"
