from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = ROOT / "apps/api/app/services/enterprise_search_runtime.py"


def _source() -> str:
    return RUNTIME_PATH.read_text(encoding="utf-8")


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(_source())
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def test_enterprise_search_runtime_has_no_legacy_python_ranking_engine() -> None:
    source = _source()

    assert "deterministic_lexical_v1" not in source
    assert "def search_published_chunks" not in source
    assert "def _score_record" not in source
    assert "class EnterpriseSearchResult" not in source
    assert "class EnterpriseSearchCitation" not in source


def test_enterprise_search_runtime_executes_postgresql_fts_path() -> None:
    build_source = ast.unparse(_function("build_enterprise_search"))
    serialize_source = ast.unparse(_function("serialize_enterprise_search_result"))

    assert "build_knowledge_fts_search(" in build_source
    assert "persist_snapshot=False" in build_source
    assert "'ranking_model': 'postgres_ts_rank_cd_simple_v1'" in serialize_source
    assert "search_published_chunks(" not in build_source
