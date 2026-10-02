"""Assistant Response runtime."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantLlmExecution,
    AssistantResponse,
    Conversation,
    ConversationTurn,
)
from app.repositories.assistant import AssistantRepository
from app.services.assistant_response_gateway import build_assistant_response_gateway, build_assistant_response_health

VISIBLE_CITATION_ID_PATTERN = re.compile(r"\s*\[citation:[A-Za-z0-9_.:-]+\]")
ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT = "uq_ai_assistant_responses_citation_verification"
_RESPONSE_OBSERVABILITY_FIELDS = {
    "correlation_id",
    "trace_id",
    "request_id",
    "timestamp",
    "created_at",
    "updated_at",
    "idempotency_input_fingerprint",
}
_RESPONSE_DERIVED_FIELDS = {
    "assistant_response_prepared",
    "final_response_created",
    "citation_verification_completed",
    "postgresql_source_of_truth",
    "llm_used",
    "embeddings_used",
    "provider_called",
    "tool_called",
    "workflow_executed",
    "external_action_called",
    "autonomous_execution",
    "response_runtime_version",
}


def _response_authoritative_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _response_authoritative_metadata(item)
            for key, item in value.items()
            if key not in _RESPONSE_OBSERVABILITY_FIELDS and key not in _RESPONSE_DERIVED_FIELDS
        }
    if isinstance(value, list):
        return [_response_authoritative_metadata(item) for item in value]
    return value


def _response_request_fingerprint(metadata: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        _response_authoritative_metadata(dict(metadata or {})),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_assistant_response_idempotency_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name == ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT


def _response_matches_scoped_pipeline(
    repository: AssistantRepository,
    response: AssistantResponse,
    citation_verification: AssistantCitationVerification,
    *,
    organization_id: uuid.UUID | None,
    request_fingerprint: str,
) -> bool:
    execution = repository.get_scoped_artifact(
        AssistantLlmExecution,
        AssistantLlmExecution.llm_execution_id,
        response.llm_execution_id,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    prompt = repository.get_prompt_package(response.prompt_package_id)
    context = repository.get_context_package(response.context_package_id)
    return bool(
        execution is not None
        and prompt is not None
        and context is not None
        and response.citation_verification_id == citation_verification.citation_verification_id
        and response.llm_execution_id == citation_verification.llm_execution_id == execution.llm_execution_id
        and response.prompt_package_id == citation_verification.prompt_package_id == execution.prompt_package_id
        and response.context_package_id == citation_verification.context_package_id == prompt.context_package_id
        and prompt.context_package_id == context.context_package_id
        and response.assistant_id == execution.assistant_id == prompt.assistant_id == context.assistant_id
        and response.assistant_session_id
        == execution.assistant_session_id
        == prompt.assistant_session_id
        == context.assistant_session_id
        and response.organization_id
        == execution.organization_id
        == prompt.organization_id
        == context.organization_id
        == citation_verification.organization_id
        and response.ownership_scope
        == execution.ownership_scope
        == prompt.ownership_scope
        == context.ownership_scope
        == citation_verification.ownership_scope
        and response.response_status == "completed"
        and (
            (response.response_metadata or {}).get("idempotency_input_fingerprint")
            or _response_request_fingerprint(response.response_metadata)
        )
        == request_fingerprint
        and response.response_text == _final_response_text(execution.raw_output_text)
        and list(response.ordered_citations or []) == list(context.ordered_citations or [])
        and response.verified_citation_count == citation_verification.verified_citation_count
        and response.missing_citation_count == citation_verification.missing_citation_count
        and response.invalid_citation_count == citation_verification.invalid_citation_count
        and response.citation_verification_passed == (int(citation_verification.invalid_citation_count or 0) == 0)
    )


def _response_input_conflict(citation_verification_id: uuid.UUID) -> dict[str, Any]:
    return {
        "assistant_response_schema_version": "1",
        "assistant_response_prepared": False,
        "final_response_created": False,
        "passed": False,
        "blocking_issues": [
            {
                "code": "assistant_response_idempotency_conflict",
                "severity": "blocking",
                "component": "assistant_response_runtime",
                "item_id": str(citation_verification_id),
                "message": "Persisted response differs from authoritative citation or LLM evidence.",
            }
        ],
        "warnings": [],
    }


def _final_response_text(raw_output_text: str | None) -> str:
    return VISIBLE_CITATION_ID_PATTERN.sub("", str(raw_output_text or "")).strip()


def assistant_response_to_dict(record: AssistantResponse) -> dict[str, Any]:
    return {
        "id": str(record.assistant_response_id),
        "assistant_response_id": str(record.assistant_response_id),
        "citation_verification_id": str(record.citation_verification_id),
        "llm_execution_id": str(record.llm_execution_id),
        "prompt_package_id": str(record.prompt_package_id),
        "context_package_id": str(record.context_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "response_status": record.response_status,
        "response_text": record.response_text,
        "response_format": record.response_format,
        "response_language": record.response_language,
        "citation_verification_passed": bool(record.citation_verification_passed),
        "verified_citation_count": int(record.verified_citation_count or 0),
        "missing_citation_count": int(record.missing_citation_count or 0),
        "invalid_citation_count": int(record.invalid_citation_count or 0),
        "ordered_citations": list(record.ordered_citations or []),
        "response_metadata": record.response_metadata or {},
        "assistant_response_prepared": True,
        "final_response_created": True,
        "citation_verification_completed": True,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _response_conversation_context(db: Session, record: AssistantResponse) -> dict[str, Any]:
    turn = db.scalar(
        select(ConversationTurn)
        .where(ConversationTurn.assistant_response_id == record.assistant_response_id)
        .order_by(ConversationTurn.created_at.asc(), ConversationTurn.conversation_turn_id.asc())
        .limit(1)
    )
    conversation = db.get(Conversation, turn.conversation_id) if turn is not None else None
    lineage_organization_ids = {
        str(value)
        for value in (
            record.organization_id,
            turn.organization_id if turn is not None else None,
            conversation.organization_id if conversation is not None else None,
        )
        if value is not None
    }
    lineage_complete = bool(
        turn is not None
        and conversation is not None
        and turn.ownership_scope != "legacy_unscoped"
        and conversation.ownership_scope != "legacy_unscoped"
    )
    return {
        "conversation_id": str(conversation.conversation_id) if conversation is not None else None,
        "turn_id": str(turn.conversation_turn_id) if turn is not None else None,
        "organization_id": str(conversation.organization_id) if conversation is not None else None,
        "lineage_complete": lineage_complete,
        "lineage_consistent": len(lineage_organization_ids) <= 1,
    }


def _response_payload(
    *,
    record: AssistantResponse,
    gateway: dict[str, Any],
    warnings: list[dict[str, Any]],
    runtime_persistence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response_dict = assistant_response_to_dict(record)
    payload = {
        "assistant_response_schema_version": "1",
        "assistant_response_prepared": True,
        "assistant_response_gateway": gateway,
        "assistant_response": response_dict,
        "id": str(record.assistant_response_id),
        "assistant_response_id": str(record.assistant_response_id),
        "citation_verification_id": str(record.citation_verification_id),
        "llm_execution_id": str(record.llm_execution_id),
        "prompt_package_id": str(record.prompt_package_id),
        "context_package_id": str(record.context_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "response_status": record.response_status,
        "response_text": record.response_text,
        "response_format": record.response_format,
        "response_language": record.response_language,
        "citation_verification_passed": bool(record.citation_verification_passed),
        "verified_citation_count": int(record.verified_citation_count or 0),
        "missing_citation_count": int(record.missing_citation_count or 0),
        "invalid_citation_count": int(record.invalid_citation_count or 0),
        "ordered_citations": list(record.ordered_citations or []),
        "response_metadata": record.response_metadata or {},
        "final_response_created": True,
        "citation_verification_completed": True,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": True,
        "blocking_issues": [],
        "warnings": warnings,
    }
    if runtime_persistence is not None:
        payload["runtime_persistence"] = runtime_persistence
    return payload


def build_assistant_response_runtime(
    db: Session,
    *,
    citation_verification_id: str,
    organization_id: uuid.UUID | None = None,
    response_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    scoped_repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(citation_verification_id))
    except (TypeError, ValueError):
        return None
    scoped_artifact = scoped_repository.get_scoped_artifact(
        AssistantCitationVerification,
        AssistantCitationVerification.citation_verification_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if scoped_artifact is None or (scoped_artifact.ownership_scope == "organization" and organization_id is None):
        return None
    gateway = build_assistant_response_gateway(
        db, citation_verification_id=citation_verification_id, response_metadata=response_metadata
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_response_schema_version": "1",
            "assistant_response_prepared": False,
            "assistant_response_gateway": gateway,
            "final_response_created": False,
            "citation_verification_completed": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    try:
        verification_uuid = uuid.UUID(str(citation_verification_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    request_fingerprint = _response_request_fingerprint(response_metadata)
    existing = repository.list_assistant_responses_by_citation_verification(
        citation_verification_id=verification_uuid, limit=1
    )
    if existing:
        response = existing[0]
        if not _response_matches_scoped_pipeline(
            repository,
            response,
            scoped_artifact,
            organization_id=organization_id,
            request_fingerprint=request_fingerprint,
        ):
            return _response_input_conflict(scoped_artifact.citation_verification_id)
        repository.mark_llm_execution_final_response_created(response.llm_execution_id)
        repository.mark_prompt_package_answer_generated(response.prompt_package_id)
        db.commit()
        payload = _response_payload(record=response, gateway=gateway, warnings=gateway.get("warnings") or [])
        if persist_snapshot:
            from app.services.runtime_persistence_runtime import persist_runtime_outputs

            payload["runtime_persistence"] = persist_runtime_outputs(
                db,
                execution_id=f"assistant-response:{response.assistant_response_id}",
                artifact_id=None,
                runtime_outputs={"assistant_response": payload},
            )
            payload["runtime_persistence"] = {
                **payload["runtime_persistence"],
                "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
            }
        return payload
    citation_verification = scoped_artifact
    if citation_verification is None:
        return None
    llm_execution = repository.get_llm_execution(citation_verification.llm_execution_id)
    prompt_package = repository.get_prompt_package(citation_verification.prompt_package_id)
    context_package = repository.get_context_package(citation_verification.context_package_id)
    if llm_execution is None or prompt_package is None or context_package is None:
        return None
    response_text = _final_response_text(llm_execution.raw_output_text)
    if not response_text:
        return {
            "assistant_response_schema_version": "1",
            "assistant_response_prepared": False,
            "assistant_response_gateway": gateway,
            "final_response_created": False,
            "citation_verification_completed": True,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "passed": False,
            "blocking_issues": [
                {
                    "code": "response_text_empty",
                    "severity": "blocking",
                    "component": "assistant_response_runtime",
                    "item_id": str(llm_execution.llm_execution_id),
                    "message": "Assistant response requires non-empty raw_output_text.",
                }
            ],
            "warnings": gateway.get("warnings") or [],
        }
    citation_verification_passed = int(citation_verification.invalid_citation_count or 0) == 0
    try:
        with db.begin_nested():
            response = repository.create_assistant_response(
                citation_verification_id=citation_verification.citation_verification_id,
                llm_execution_id=llm_execution.llm_execution_id,
                prompt_package_id=prompt_package.prompt_package_id,
                context_package_id=context_package.context_package_id,
                assistant_id=llm_execution.assistant_id,
                assistant_session_id=llm_execution.assistant_session_id,
                response_status="completed",
                response_text=response_text,
                response_format="markdown",
                response_language="unknown",
                citation_verification_passed=citation_verification_passed,
                verified_citation_count=int(citation_verification.verified_citation_count or 0),
                missing_citation_count=int(citation_verification.missing_citation_count or 0),
                invalid_citation_count=int(citation_verification.invalid_citation_count or 0),
                ordered_citations=list(context_package.ordered_citations or []),
                response_metadata={
                    **dict(response_metadata or {}),
                    "assistant_response_prepared": True,
                    "final_response_created": True,
                    "citation_verification_completed": True,
                    "postgresql_source_of_truth": True,
                    "llm_used": False,
                    "embeddings_used": False,
                    "provider_called": False,
                    "tool_called": False,
                    "workflow_executed": False,
                    "external_action_called": False,
                    "autonomous_execution": False,
                    "response_runtime_version": "assistant_response_runtime/1",
                    "idempotency_input_fingerprint": request_fingerprint,
                },
            )
    except IntegrityError as exc:
        if not _is_assistant_response_idempotency_conflict(exc):
            raise
        existing = repository.list_assistant_responses_by_citation_verification(
            citation_verification_id=verification_uuid,
            limit=1,
        )
        if not existing:
            raise
        response = existing[0]
        if not _response_matches_scoped_pipeline(
            repository,
            response,
            scoped_artifact,
            organization_id=organization_id,
            request_fingerprint=request_fingerprint,
        ):
            return _response_input_conflict(scoped_artifact.citation_verification_id)
    repository.mark_llm_execution_final_response_created(llm_execution.llm_execution_id)
    repository.mark_prompt_package_answer_generated(prompt_package.prompt_package_id)
    db.commit()
    payload = _response_payload(record=response, gateway=gateway, warnings=gateway.get("warnings") or [])
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-response:{response.assistant_response_id}",
            artifact_id=None,
            runtime_outputs={"assistant_response": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_response(
    db: Session, assistant_response_id: str, *, organization_id: str | None = None
) -> dict[str, Any] | None:
    try:
        response_uuid = uuid.UUID(str(assistant_response_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    record = repository.get_scoped_artifact(
        AssistantResponse,
        AssistantResponse.assistant_response_id,
        response_uuid,
        organization_id=uuid.UUID(organization_id) if organization_id else None,
        platform_scope=organization_id is None,
    )
    if record is None:
        return None
    context = _response_conversation_context(db, record)
    if not context["lineage_complete"]:
        return {
            "assistant_response_schema_version": "1",
            "assistant_response_id": str(record.assistant_response_id),
            "assistant_response_read_allowed": False,
            "passed": False,
            "blocking_issues": [
                {
                    "code": "RESOURCE_LINEAGE_INCOMPLETE",
                    "severity": "blocking",
                    "component": "assistant_response_read",
                    "item_id": str(record.assistant_response_id),
                    "message": "Assistant response conversation lineage is incomplete.",
                }
            ],
            "warnings": [],
        }
    if not context["lineage_consistent"] or (
        organization_id and context.get("organization_id") and str(organization_id) != str(context["organization_id"])
    ):
        return {
            "assistant_response_schema_version": "1",
            "assistant_response_id": str(record.assistant_response_id),
            "assistant_response_read_allowed": False,
            "passed": False,
            "blocking_issues": [
                {
                    "code": "CROSS_ORGANIZATION_ACCESS_DETECTED",
                    "severity": "blocking",
                    "component": "assistant_response_read",
                    "item_id": str(record.assistant_response_id),
                    "message": "Assistant response ownership does not match its conversation lineage.",
                }
            ],
            "warnings": [],
        }
    response = assistant_response_to_dict(record)
    response.update(context)
    response["assistant_response_read_allowed"] = True
    return response


__all__ = [
    "assistant_response_to_dict",
    "build_assistant_response_health",
    "build_assistant_response_runtime",
    "read_assistant_response",
]
