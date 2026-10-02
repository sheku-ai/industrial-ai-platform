from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function(path: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(_source(path))
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def test_fts_facets_share_operational_document_scope_with_search_results() -> None:
    source = ast.unparse(_function("apps/api/app/repositories/knowledge_index.py", "search_fts_facets"))

    assert "KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String)" in source
    assert "self._operational_document_criteria()" in source
    assert "DocumentRecord.organization_id == organization_uuid" in source
