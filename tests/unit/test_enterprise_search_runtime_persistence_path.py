from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_PATH = Path("apps/api/app/services/enterprise_search_runtime.py")


def _runtime_tree() -> ast.Module:
    return ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))


def test_runtime_uses_canonical_enterprise_search_persistence_helper() -> None:
    tree = _runtime_tree()
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_enterprise_search"
    )
    helper_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "persist_enterprise_search_result"
    ]

    assert len(helper_calls) == 1
    keyword_names = {keyword.arg for keyword in helper_calls[0].keywords}
    assert keyword_names == {
        "organization_id",
        "query",
        "offset",
        "limit",
        "top_k",
        "filters",
        "include_facets",
        "include_debug",
        "result",
    }


def test_runtime_has_no_alternate_persistence_identity_algorithm() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")

    assert "_stable_digest" not in source
    assert "import hashlib" not in source
    assert "persist_runtime_outputs" not in source
