"""Assistant Response validation gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_response_gateway(
    db: Session,
    *,
    citation_verification_id: str,
    response_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    citation_verification = None
    llm_execution = None
    prompt_package = None
    context_package = None
    existing_response = None
    try:
        verification_uuid = uuid.UUID(str(citation_verification_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "citation_verification_id_invalid",
                "Assistant response requires a valid citation_verification_id.",
                component="assistant_response_gateway",
                item_id=str(citation_verification_id),
            )
        )
    else:
        citation_verification = repository.get_citation_verification(verification_uuid)
        if citation_verification is None:
            blocking_issues.append(
                issue(
                    "citation_verification_not_found",
                    "Assistant response requires an existing citation verification.",
                    component="assistant_response_gateway",
                    item_id=str(verification_uuid),
                )
            )
        else:
            existing = repository.list_assistant_responses_by_citation_verification(
                citation_verification_id=verification_uuid, limit=1
            )
            if existing:
                existing_response = existing[0]
                warnings.append(
                    issue(
                        "assistant_response_already_exists",
                        "Assistant response already exists for this citation verification.",
                        component="assistant_response_gateway",
                        severity="warning",
                        item_id=str(existing_response.assistant_response_id),
                    )
                )
            llm_execution = repository.get_llm_execution(citation_verification.llm_execution_id)
            if llm_execution is None:
                blocking_issues.append(
                    issue(
                        "llm_execution_not_found",
                        "Assistant response requires an existing LLM execution.",
                        component="assistant_response_gateway",
                        item_id=str(citation_verification.llm_execution_id),
                    )
                )
            prompt_package = repository.get_prompt_package(citation_verification.prompt_package_id)
            if prompt_package is None:
                blocking_issues.append(
                    issue(
                        "prompt_package_not_found",
                        "Assistant response requires an existing prompt package.",
                        component="assistant_response_gateway",
                        item_id=str(citation_verification.prompt_package_id),
                    )
                )
            context_package = repository.get_context_package(citation_verification.context_package_id)
            if context_package is None:
                blocking_issues.append(
                    issue(
                        "context_package_not_found",
                        "Assistant response requires an existing context package.",
                        component="assistant_response_gateway",
                        item_id=str(citation_verification.context_package_id),
                    )
                )
    if llm_execution is not None and llm_execution.execution_status != "completed":
        blocking_issues.append(
            issue(
                "llm_execution_not_completed",
                "Assistant response requires a completed LLM execution.",
                component="assistant_response_gateway",
                item_id=llm_execution.execution_status,
            )
        )
    if citation_verification is not None and citation_verification.verification_status != "completed":
        blocking_issues.append(
            issue(
                "citation_verification_not_completed",
                "Assistant response requires a completed citation verification.",
                component="assistant_response_gateway",
                item_id=citation_verification.verification_status,
            )
        )
    if llm_execution is not None and not str(llm_execution.raw_output_text or "").strip():
        blocking_issues.append(
            issue(
                "raw_output_text_missing",
                "Assistant response requires non-empty raw_output_text.",
                component="assistant_response_gateway",
                item_id=str(llm_execution.llm_execution_id),
            )
        )
    ready = not blocking_issues
    return {
        "assistant_response_gateway_schema_version": "1",
        "assistant_response_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "citation_verification_id": str(citation_verification.citation_verification_id)
        if citation_verification is not None
        else str(citation_verification_id),
        "llm_execution_id": str(llm_execution.llm_execution_id) if llm_execution is not None else None,
        "prompt_package_id": str(prompt_package.prompt_package_id) if prompt_package is not None else None,
        "context_package_id": str(context_package.context_package_id) if context_package is not None else None,
        "assistant_id": str(llm_execution.assistant_id) if llm_execution is not None else None,
        "assistant_session_id": str(llm_execution.assistant_session_id)
        if llm_execution is not None and llm_execution.assistant_session_id
        else None,
        "existing_response_id": str(existing_response.assistant_response_id) if existing_response is not None else None,
        "assistant_response_prepared": ready,
        "final_response_created": existing_response is not None,
        "citation_verification_completed": citation_verification.verification_status == "completed"
        if citation_verification is not None
        else False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "create_assistant_response",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_response_gateway_blocked",
            }
        ],
        "response_metadata": dict(response_metadata or {}),
    }


def build_assistant_response_health(db: Session) -> dict[str, Any]:
    return {
        "assistant_response_health_schema_version": "1",
        "assistant_response_available": True,
        "assistant_response_status": "deterministic_response_runtime",
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
