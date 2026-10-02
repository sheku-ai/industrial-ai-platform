"""Assistant Citation Verification validation gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_citation_verification_contracts import AssistantCitationVerificationHealthResult
from app.services.assistant_citation_verification_session import (
    build_assistant_citation_verification_request,
    build_assistant_citation_verification_session,
    serialize_assistant_citation_verification_session,
)
from app.services.enterprise_search_session import issue, sort_issues


def build_assistant_citation_verification_gateway(
    db: Session,
    *,
    llm_execution_id: str,
    request_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    llm_execution = None
    prompt_package = None
    context_package = None
    try:
        execution_uuid = uuid.UUID(str(llm_execution_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            issue(
                "llm_execution_id_invalid",
                "Assistant citation verification requires a valid llm_execution_id.",
                component="assistant_citation_verification_gateway",
                item_id=str(llm_execution_id),
            )
        )
    else:
        llm_execution = repository.get_llm_execution(execution_uuid)
        if llm_execution is None:
            blocking_issues.append(
                issue(
                    "llm_execution_not_found",
                    "Assistant citation verification requires an existing LLM execution.",
                    component="assistant_citation_verification_gateway",
                    item_id=str(execution_uuid),
                )
            )
        else:
            prompt_package = repository.get_prompt_package(llm_execution.prompt_package_id)
            if prompt_package is None:
                blocking_issues.append(
                    issue(
                        "prompt_package_not_found",
                        "Assistant citation verification requires an existing prompt package.",
                        component="assistant_citation_verification_gateway",
                        item_id=str(llm_execution.prompt_package_id),
                    )
                )
            else:
                context_package = repository.get_context_package(prompt_package.context_package_id)
                if context_package is None:
                    blocking_issues.append(
                        issue(
                            "context_package_not_found",
                            "Assistant citation verification requires an existing context package.",
                            component="assistant_citation_verification_gateway",
                            item_id=str(prompt_package.context_package_id),
                        )
                    )
    request = build_assistant_citation_verification_request(
        llm_execution_id=str(llm_execution_id),
        prompt_package_id=str(prompt_package.prompt_package_id) if prompt_package is not None else "",
        context_package_id=str(context_package.context_package_id) if context_package is not None else "",
        assistant_runtime_id=None,
        raw_output_available=bool(llm_execution.raw_output_text) if llm_execution is not None else False,
        context_citation_count=int(context_package.citation_count or 0) if context_package is not None else 0,
        request_metadata=request_metadata,
    )
    session = serialize_assistant_citation_verification_session(build_assistant_citation_verification_session(request))
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    if llm_execution is not None and llm_execution.execution_status != "completed":
        blocking_issues.append(
            issue(
                "llm_execution_not_completed",
                "Assistant citation verification requires a completed LLM execution.",
                component="assistant_citation_verification_gateway",
                item_id=llm_execution.execution_status,
            )
        )
    if llm_execution is not None and not bool(llm_execution.provider_called):
        blocking_issues.append(
            issue(
                "llm_provider_not_called",
                "Assistant citation verification requires raw output from a called provider.",
                component="assistant_citation_verification_gateway",
                item_id=str(llm_execution.llm_execution_id),
            )
        )
    if prompt_package is not None and prompt_package.package_status not in {"created", "prepared"}:
        blocking_issues.append(
            issue(
                "prompt_package_status_not_ready",
                "Assistant citation verification requires a created prompt package.",
                component="assistant_citation_verification_gateway",
                item_id=prompt_package.package_status,
            )
        )
    if context_package is not None and context_package.package_status not in {"created", "prepared"}:
        blocking_issues.append(
            issue(
                "context_package_status_not_ready",
                "Assistant citation verification requires a created context package.",
                component="assistant_citation_verification_gateway",
                item_id=context_package.package_status,
            )
        )
    ready = bool(session.get("assistant_citation_verification_session_ready")) and not blocking_issues
    return {
        "assistant_citation_verification_gateway_schema_version": "1",
        "assistant_citation_verification_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_citation_verification_session": session,
        "llm_execution_id": str(llm_execution.llm_execution_id) if llm_execution is not None else str(llm_execution_id),
        "prompt_package_id": str(prompt_package.prompt_package_id) if prompt_package is not None else None,
        "context_package_id": str(context_package.context_package_id) if context_package is not None else None,
        "assistant_runtime_id": None,
        "citation_runtime_created": False,
        "verification_completed": False,
        "verified_citation_count": 0,
        "missing_citation_count": 0,
        "invalid_citation_count": 0,
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "verify_assistant_citations",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "assistant_citation_verification_gateway_blocked",
            }
        ],
    }


def build_assistant_citation_verification_health(db: Session) -> dict[str, Any]:
    return AssistantCitationVerificationHealthResult().as_dict()
