from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_PATH = ROOT / "apps/api/app/repositories/knowledge_index.py"


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(REPOSITORY_PATH.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def test_indexed_chunk_count_uses_operational_search_universe() -> None:
    source = ast.unparse(_function("indexed_chunk_count"))

    assert "KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String)" in source
    assert "*self._operational_document_criteria()" in source
    assert "DocumentRecord.organization_id == organization_uuid" in source


def test_indexed_chunk_count_does_not_conditionally_join_document_record() -> None:
    function = _function("indexed_chunk_count")
    conditional_sources = [ast.unparse(node) for node in ast.walk(function) if isinstance(node, ast.If)]

    assert not any(".join(DocumentRecord" in source for source in conditional_sources)
