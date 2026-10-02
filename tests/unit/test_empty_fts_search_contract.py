from __future__ import annotations

from app.services.assistant_search_execution_runtime import _assistant_context_acceptance_issues
from app.services.enterprise_search_runtime import EnterpriseSearchRuntimeResult, serialize_enterprise_search_result
from app.services.knowledge_fts_runtime import (
    FTS_SEARCH_STATUS_COMPLETED,
    KnowledgeFtsRuntimeResult,
    serialize_knowledge_fts_result,
    validate_fts_results,
)


def test_empty_fts_results_are_a_valid_completed_search_without_matches() -> None:
    validation = validate_fts_results([], [])
    payload = serialize_knowledge_fts_result(
        KnowledgeFtsRuntimeResult(
            fts_session_id="fts-session:test",
            fts_search_status=FTS_SEARCH_STATUS_COMPLETED,
            query="nonexistent term",
            normalized_query="nonexistent term",
            fts_validation=validation,
        )
    )

    assert validation["valid"] is True
    assert validation["validation_status"] == "valid"
    assert validation["matches_found"] is False
    assert validation["blocking_issues"] == []
    assert payload["fts_search_completed"] is True
    assert payload["fts_search_succeeded"] is True
    assert payload["fts_search_used"] is True
    assert payload["search_uses_postgresql_fts"] is True
    assert payload["matches_found"] is False


def test_empty_enterprise_search_preserves_technical_fts_execution_state() -> None:
    payload = serialize_enterprise_search_result(
        EnterpriseSearchRuntimeResult(
            search_session_id="search-session:test",
            search_status="completed",
            query="nonexistent term",
            normalized_query="nonexistent term",
        )
    )

    assert payload["search_completed"] is True
    assert payload["search_succeeded"] is True
    assert payload["search_uses_postgresql_fts"] is True
    assert payload["matches_found"] is False


def test_empty_search_is_rejected_only_for_assistant_context_acceptance() -> None:
    issues = _assistant_context_acceptance_issues(
        search_completed=True,
        result_count=0,
        postgresql_fts_used=True,
    )

    assert [item["code"] for item in issues] == ["search_results_empty"]
    assert issues[0]["component"] == "assistant_search_execution"


def test_nonempty_search_is_eligible_for_assistant_context() -> None:
    assert (
        _assistant_context_acceptance_issues(
            search_completed=True,
            result_count=1,
            postgresql_fts_used=True,
        )
        == []
    )
