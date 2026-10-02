"""Conversation Runtime."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import Conversation, ConversationTurn
from app.models.conversation_interaction_plan import ConversationInteractionPlan
from app.repositories.assistant import AssistantRepository
from app.services.conversation_context_runtime import (
    conversation_context_package_to_dict,
    resolve_conversation_context_package,
)
from app.services.conversation_gateway import (
    validate_assistant_response_attachment,
    validate_conversation_creation,
    validate_conversation_turn_creation,
)
from app.services.conversation_interaction_runtime import (
    interaction_decision_to_dict,
    resolve_interaction_decision,
)

CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT = "uq_ai_conversation_turns_chat_request"
CONVERSATION_TURN_INDEX_CONSTRAINT = "uq_ai_conversation_turns_conversation_index"
ASSISTANT_RESPONSE_TURN_IDENTITY_CONSTRAINT = "uq_ai_conversation_turns_response_identity"
DETERMINISTIC_TURN_IDENTITY_CONSTRAINT = "uq_ai_conversation_turns_deterministic_operation"


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _is_chat_request_retry_conflict(exc: IntegrityError) -> bool:
    return _integrity_constraint_name(exc) in {
        CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT,
        CONVERSATION_TURN_INDEX_CONSTRAINT,
    }


def find_chat_request_turn(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    request_id: str,
) -> ConversationTurn | None:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    return db.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.organization_id == organization_id,
            ConversationTurn.assistant_id == assistant_id,
            ConversationTurn.turn_role == "user",
            ConversationTurn.request_id == normalized_request_id,
        )
        .order_by(ConversationTurn.created_at.asc())
        .limit(1)
    )


def _lock_scoped_conversation_for_turn_write(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Conversation | None:
    return db.scalar(
        select(Conversation)
        .where(
            Conversation.conversation_id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.ownership_scope == "organization",
        )
        .with_for_update()
    )


def conversation_to_dict(record: Conversation) -> dict[str, Any]:
    return {
        "conversation_id": str(record.conversation_id),
        "organization_id": str(record.organization_id) if record.organization_id else None,
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "assistant_id": str(record.assistant_id) if record.assistant_id else None,
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "conversation_status": record.conversation_status,
        "conversation_title": record.conversation_title,
        "conversation_reference": record.conversation_reference,
        "requested_by": record.requested_by,
        "runtime_context": record.runtime_context or {},
        "conversation_metadata": record.conversation_metadata or {},
        "conversation_created": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def conversation_turn_to_dict(record: ConversationTurn) -> dict[str, Any]:
    deterministic_plan_id = getattr(record, "deterministic_interaction_plan_id", None)
    return {
        "conversation_turn_id": str(record.conversation_turn_id),
        "organization_id": str(record.organization_id) if record.organization_id else None,
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "conversation_id": str(record.conversation_id),
        "assistant_id": str(record.assistant_id) if record.assistant_id else None,
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "assistant_run_id": str(record.assistant_run_id) if record.assistant_run_id else None,
        "assistant_runtime_trace_available": bool(record.assistant_run_id),
        "assistant_response_id": str(record.assistant_response_id) if record.assistant_response_id else None,
        "deterministic_interaction_plan_id": str(deterministic_plan_id) if deterministic_plan_id else None,
        "deterministic_input_fingerprint": getattr(record, "deterministic_input_fingerprint", None),
        "turn_index": int(record.turn_index or 0),
        "turn_role": record.turn_role,
        "turn_status": record.turn_status,
        "input_text": record.input_text,
        "output_text": record.output_text,
        "response_format": record.response_format,
        "citation_summary": record.citation_summary or {},
        "ordered_citations": list(record.ordered_citations or []),
        "turn_metadata": record.turn_metadata or {},
        "conversation_turn_created": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _persist_snapshot(db: Session, *, execution_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.runtime_persistence_runtime import persist_runtime_outputs

    result = persist_runtime_outputs(
        db,
        execution_id=execution_id,
        artifact_id=None,
        runtime_outputs={"conversation_runtime": payload},
    )
    return {**result, "runtime_persistence": bool(result.get("persistence_completed"))}


def build_conversation_runtime(
    db: Session,
    *,
    assistant_id: str | None = None,
    assistant_session_id: str | None = None,
    conversation_title: str | None = None,
    conversation_reference: str | None = None,
    requested_by: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    conversation_metadata: dict[str, Any] | None = None,
    organization_id: uuid.UUID,
    data_origin: str,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = validate_conversation_creation(
        db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        conversation_status="active",
    )
    if gateway.get("blocking_issues"):
        return {
            "conversation_runtime_schema_version": "1",
            "conversation_runtime_prepared": False,
            "conversation_gateway": gateway,
            "conversation_created": False,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "embeddings_used": False,
            "provider_called": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    assistant_uuid = uuid.UUID(gateway["assistant_id"]) if gateway.get("assistant_id") else None
    session_uuid = uuid.UUID(gateway["assistant_session_id"]) if gateway.get("assistant_session_id") else None
    repository = AssistantRepository(db)
    if (
        assistant_uuid is not None
        and repository.get_scoped_assistant_definition(assistant_uuid, organization_id=organization_id) is None
    ):
        return {
            "conversation_runtime_schema_version": "1",
            "conversation_runtime_prepared": False,
            "conversation_created": False,
            "postgresql_source_of_truth": True,
            "passed": False,
            "blocking_issues": [
                {
                    "code": "assistant_not_authorized_for_organization",
                    "severity": "blocking",
                    "component": "conversation_runtime",
                    "message": "Assistant is not available in the authorized organization scope.",
                }
            ],
            "warnings": [],
        }
    conversation = repository.create_conversation(
        organization_id=organization_id,
        data_origin=data_origin,
        assistant_id=assistant_uuid,
        assistant_session_id=session_uuid,
        conversation_status="active",
        conversation_title=conversation_title,
        conversation_reference=conversation_reference,
        requested_by=requested_by,
        runtime_context=runtime_context,
        conversation_metadata={
            **dict(conversation_metadata or {}),
            "conversation_runtime_prepared": True,
            "conversation_created": True,
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "embeddings_used": False,
            "provider_called": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
        },
    )
    db.commit()
    payload = {
        "conversation_runtime_schema_version": "1",
        "conversation_runtime_prepared": True,
        "conversation_gateway": gateway,
        "conversation": conversation_to_dict(conversation),
        "conversation_id": str(conversation.conversation_id),
        "conversation_created": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        payload["runtime_persistence"] = _persist_snapshot(
            db, execution_id=f"conversation-runtime:{conversation.conversation_id}", payload=payload
        )
    return payload


def read_conversation(db: Session, conversation_id: str, *, organization_id: uuid.UUID) -> dict[str, Any] | None:
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_scoped_conversation(conversation_uuid, organization_id=organization_id)
    return conversation_to_dict(record) if record is not None else None


def list_conversations_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assistant_id: str | None = None,
    conversation_status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    assistant_uuid = uuid.UUID(str(assistant_id)) if assistant_id else None
    records = AssistantRepository(db).list_scoped_conversations(
        organization_id=organization_id,
        assistant_id=assistant_uuid,
        conversation_status=conversation_status,
        limit=limit,
    )
    return {
        "conversation_runtime_schema_version": "1",
        "conversation_runtime_prepared": True,
        "conversations": [conversation_to_dict(record) for record in records],
        "count": len(records),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }


def _deterministic_turn_fingerprint(
    db: Session,
    *,
    plan_id: uuid.UUID,
    conversation: Conversation,
    organization_id: uuid.UUID,
    turn_role: str,
    turn_metadata: dict[str, Any] | None,
) -> str:
    plan = db.get(ConversationInteractionPlan, plan_id)
    if plan is None:
        raise ValueError("authoritative deterministic interaction plan is unavailable")
    user_turn = db.get(ConversationTurn, plan.conversation_turn_id)
    if (
        turn_role != "assistant"
        or plan.organization_id != organization_id
        or plan.conversation_id != conversation.conversation_id
        or plan.ownership_scope != "organization"
        or user_turn is None
        or user_turn.turn_role != "user"
        or user_turn.organization_id != organization_id
        or user_turn.conversation_id != conversation.conversation_id
        or user_turn.assistant_id != conversation.assistant_id
        or user_turn.assistant_session_id != conversation.assistant_session_id
    ):
        raise ValueError("deterministic turn plan, user turn, or conversation lineage is inconsistent")
    metadata = dict(turn_metadata or {})
    if metadata.get("interaction_plan_id") and str(metadata["interaction_plan_id"]) != str(plan_id):
        raise ValueError("deterministic turn interaction plan identity is inconsistent")
    if metadata.get("conversation_turn_id") and str(metadata["conversation_turn_id"]) != str(
        user_turn.conversation_turn_id
    ):
        raise ValueError("deterministic turn user identity is inconsistent")
    if metadata.get("planned_action") and metadata["planned_action"] != plan.planned_action:
        raise ValueError("deterministic turn action is inconsistent with persisted plan")
    if not (metadata.get("conversation_no_search_runtime") or metadata.get("no_evidence_response")):
        raise ValueError("deterministic turn identity requires a no-search outcome")
    if metadata.get("conversation_no_search_runtime") and plan.enterprise_search_required:
        raise ValueError("no-search outcome contradicts persisted search plan")
    if metadata.get("no_evidence_response") and not plan.enterprise_search_required:
        raise ValueError("no-evidence outcome contradicts persisted no-search plan")
    payload = {
        "organization_id": str(organization_id),
        "assistant_id": str(conversation.assistant_id),
        "assistant_session_id": str(conversation.assistant_session_id) if conversation.assistant_session_id else None,
        "conversation_id": str(conversation.conversation_id),
        "user_turn_id": str(user_turn.conversation_turn_id),
        "user_input": user_turn.input_text,
        "chat_input_fingerprint": (user_turn.turn_metadata or {}).get("chat_input_fingerprint"),
        "interaction_plan_id": str(plan_id),
        "planned_action": plan.planned_action,
        "plan_input_hash": plan.input_hash,
        "plan_hash": plan.plan_hash,
        "outcome": "no_evidence" if metadata.get("no_evidence_response") else "no_search",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_deterministic_turn(db: Session, plan_id: uuid.UUID) -> ConversationTurn | None:
    return db.scalar(select(ConversationTurn).where(ConversationTurn.deterministic_interaction_plan_id == plan_id))


def _validate_deterministic_winner(
    turn: ConversationTurn,
    *,
    plan_id: uuid.UUID,
    fingerprint: str,
    conversation: Conversation,
    organization_id: uuid.UUID,
    assistant_run_id: uuid.UUID | None,
) -> None:
    if (
        turn.deterministic_interaction_plan_id != plan_id
        or turn.deterministic_input_fingerprint != fingerprint
        or turn.organization_id != organization_id
        or turn.conversation_id != conversation.conversation_id
        or turn.assistant_id != conversation.assistant_id
        or turn.assistant_session_id != conversation.assistant_session_id
        or turn.assistant_run_id != assistant_run_id
        or turn.turn_role != "assistant"
        or turn.assistant_response_id is not None
    ):
        raise ValueError("deterministic operation identity conflicts with persisted turn lineage or input")


def build_conversation_turn_runtime(
    db: Session,
    *,
    conversation_id: str,
    turn_role: str,
    input_text: str | None = None,
    output_text: str | None = None,
    assistant_run_id: str | None = None,
    response_format: str = "markdown",
    citation_summary: dict[str, Any] | None = None,
    ordered_citations: list[dict[str, Any]] | None = None,
    turn_metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
    deterministic_interaction_plan_id: str | None = None,
    organization_id: uuid.UUID,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = validate_conversation_turn_creation(
        db,
        conversation_id=conversation_id,
        turn_role=turn_role,
        assistant_run_id=assistant_run_id,
        deterministic_interaction_plan_id=deterministic_interaction_plan_id,
        organization_id=organization_id,
    )
    if gateway.get("blocking_issues"):
        return {
            "conversation_turn_runtime_schema_version": "1",
            "conversation_turn_runtime_prepared": False,
            "conversation_turn_gateway": gateway,
            "conversation_turn_created": False,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "embeddings_used": False,
            "provider_called": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = AssistantRepository(db)
    conversation_uuid = uuid.UUID(str(conversation_id))
    conversation = _lock_scoped_conversation_for_turn_write(
        db,
        conversation_id=conversation_uuid,
        organization_id=organization_id,
    )
    if conversation is None:
        return None
    deterministic_plan_id = (
        uuid.UUID(str(deterministic_interaction_plan_id)) if deterministic_interaction_plan_id else None
    )
    deterministic_marker = bool(
        turn_role == "assistant"
        and (turn_metadata or {}).get("conversation_no_search_runtime")
        or turn_role == "assistant"
        and (turn_metadata or {}).get("no_evidence_response")
    )
    if deterministic_marker and deterministic_plan_id is None:
        raise ValueError("deterministic assistant turn requires persisted interaction plan identity")
    deterministic_fingerprint = (
        _deterministic_turn_fingerprint(
            db,
            plan_id=deterministic_plan_id,
            conversation=conversation,
            organization_id=organization_id,
            turn_role=turn_role,
            turn_metadata=turn_metadata,
        )
        if deterministic_plan_id is not None
        else None
    )
    normalized_request_id = str(request_id or "").strip() or None
    if turn_role != "user":
        normalized_request_id = None
    if normalized_request_id and conversation.assistant_id is None:
        return {
            "conversation_turn_runtime_schema_version": "1",
            "conversation_turn_runtime_prepared": False,
            "conversation_turn_gateway": gateway,
            "conversation_turn_created": False,
            "postgresql_source_of_truth": True,
            "passed": False,
            "blocking_issues": ["chat_request_assistant_id_missing"],
            "warnings": gateway.get("warnings") or [],
        }
    if normalized_request_id and conversation.assistant_id is not None:
        existing_request_turn = find_chat_request_turn(
            db,
            organization_id=organization_id,
            assistant_id=conversation.assistant_id,
            request_id=normalized_request_id,
        )
        if existing_request_turn is not None:
            context_package = resolve_conversation_context_package(
                db,
                conversation_turn_id=existing_request_turn.conversation_turn_id,
                organization_id=organization_id,
            )
            if context_package is None:
                raise RuntimeError("conversation context package could not be resolved")
            interaction_decision = resolve_interaction_decision(
                db,
                conversation_turn_id=existing_request_turn.conversation_turn_id,
                organization_id=organization_id,
            )
            if interaction_decision is None:
                raise RuntimeError("conversation interaction decision could not be resolved")
            db.commit()
            return {
                "conversation_turn_runtime_schema_version": "1",
                "conversation_turn_runtime_prepared": True,
                "conversation_turn_gateway": gateway,
                "conversation_turn": conversation_turn_to_dict(existing_request_turn),
                "conversation_context": conversation_context_package_to_dict(context_package),
                "interaction_decision": interaction_decision_to_dict(interaction_decision),
                "conversation_id": str(existing_request_turn.conversation_id),
                "conversation_turn_id": str(existing_request_turn.conversation_turn_id),
                "assistant_run_id": str(existing_request_turn.assistant_run_id)
                if existing_request_turn.assistant_run_id
                else None,
                "assistant_runtime_trace_available": bool(existing_request_turn.assistant_run_id),
                "conversation_turn_created": False,
                "idempotent_replay": True,
                "postgresql_source_of_truth": True,
                "passed": True,
                "blocking_issues": [],
                "warnings": gateway.get("warnings") or [],
            }
    assistant_run_uuid: uuid.UUID | None = None
    if assistant_run_id:
        try:
            assistant_run_uuid = uuid.UUID(str(assistant_run_id))
        except (TypeError, ValueError):
            return {
                "conversation_turn_runtime_schema_version": "1",
                "conversation_turn_runtime_prepared": False,
                "conversation_turn_gateway": gateway,
                "conversation_turn_created": False,
                "assistant_run_id": None,
                "assistant_runtime_trace_available": False,
                "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
                "postgresql_source_of_truth": True,
                "llm_used": False,
                "embeddings_used": False,
                "provider_called": False,
                "tool_called": False,
                "workflow_executed": False,
                "external_action_called": False,
                "autonomous_execution": False,
                "passed": False,
                "blocking_issues": ["assistant_run_id_invalid"],
                "warnings": gateway.get("warnings") or [],
            }
        if repository.get_assistant_runtime_run(assistant_run_uuid) is None:
            return {
                "conversation_turn_runtime_schema_version": "1",
                "conversation_turn_runtime_prepared": False,
                "conversation_turn_gateway": gateway,
                "conversation_turn_created": False,
                "assistant_run_id": str(assistant_run_uuid),
                "assistant_runtime_trace_available": False,
                "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
                "postgresql_source_of_truth": True,
                "llm_used": False,
                "embeddings_used": False,
                "provider_called": False,
                "tool_called": False,
                "workflow_executed": False,
                "external_action_called": False,
                "autonomous_execution": False,
                "passed": False,
                "blocking_issues": ["assistant_run_not_found"],
                "warnings": gateway.get("warnings") or [],
            }
    existing_deterministic_turn = _find_deterministic_turn(db, deterministic_plan_id) if deterministic_plan_id else None
    if existing_deterministic_turn is not None:
        _validate_deterministic_winner(
            existing_deterministic_turn,
            plan_id=deterministic_plan_id,
            fingerprint=deterministic_fingerprint,
            conversation=conversation,
            organization_id=organization_id,
            assistant_run_id=assistant_run_uuid,
        )
    turn_created = existing_deterministic_turn is None
    turn = existing_deterministic_turn
    try:
        if existing_deterministic_turn is not None:
            pass
        elif normalized_request_id:
            with db.begin_nested():
                turn = repository.create_conversation_turn(
                    organization_id=conversation.organization_id,
                    data_origin=conversation.data_origin,
                    conversation_id=conversation.conversation_id,
                    assistant_id=conversation.assistant_id,
                    assistant_session_id=conversation.assistant_session_id,
                    assistant_run_id=assistant_run_uuid,
                    turn_index=repository.get_next_conversation_turn_index(conversation.conversation_id),
                    turn_role=turn_role,
                    turn_status="completed" if turn_role == "assistant" and output_text else "recorded",
                    input_text=input_text,
                    output_text=output_text,
                    response_format=response_format,
                    citation_summary=citation_summary,
                    ordered_citations=ordered_citations,
                    turn_metadata=turn_metadata,
                )
                turn.request_id = normalized_request_id
                db.add(turn)
                db.flush()
        elif deterministic_plan_id is not None:
            with db.begin_nested():
                turn = repository.create_conversation_turn(
                    organization_id=conversation.organization_id,
                    data_origin=conversation.data_origin,
                    conversation_id=conversation.conversation_id,
                    assistant_id=conversation.assistant_id,
                    assistant_session_id=conversation.assistant_session_id,
                    assistant_run_id=assistant_run_uuid,
                    deterministic_interaction_plan_id=deterministic_plan_id,
                    deterministic_input_fingerprint=deterministic_fingerprint,
                    turn_index=repository.get_next_conversation_turn_index(conversation.conversation_id),
                    turn_role="assistant",
                    turn_status="completed",
                    output_text=output_text,
                    response_format=response_format,
                    citation_summary=citation_summary,
                    ordered_citations=ordered_citations,
                    turn_metadata=turn_metadata,
                )
        else:
            turn = repository.create_conversation_turn(
                organization_id=conversation.organization_id,
                data_origin=conversation.data_origin,
                conversation_id=conversation.conversation_id,
                assistant_id=conversation.assistant_id,
                assistant_session_id=conversation.assistant_session_id,
                assistant_run_id=assistant_run_uuid,
                turn_index=repository.get_next_conversation_turn_index(conversation.conversation_id),
                turn_role=turn_role,
                turn_status="completed" if turn_role == "assistant" and output_text else "recorded",
                input_text=input_text,
                output_text=output_text,
                response_format=response_format,
                citation_summary=citation_summary,
                ordered_citations=ordered_citations,
                turn_metadata=turn_metadata,
            )
    except IntegrityError as exc:
        if (
            deterministic_plan_id is not None
            and _integrity_constraint_name(exc) == DETERMINISTIC_TURN_IDENTITY_CONSTRAINT
        ):
            winner = _find_deterministic_turn(db, deterministic_plan_id)
            if winner is None:
                raise
            _validate_deterministic_winner(
                winner,
                plan_id=deterministic_plan_id,
                fingerprint=deterministic_fingerprint,
                conversation=conversation,
                organization_id=organization_id,
                assistant_run_id=assistant_run_uuid,
            )
            turn = winner
            turn_created = False
        else:
            if (
                not normalized_request_id
                or conversation.assistant_id is None
                or not _is_chat_request_retry_conflict(exc)
            ):
                raise
            winner = find_chat_request_turn(
                db,
                organization_id=organization_id,
                assistant_id=conversation.assistant_id,
                request_id=normalized_request_id,
            )
            if winner is None:
                raise
            turn = winner
            turn_created = False
    if turn is None:
        raise RuntimeError("conversation turn materialization did not return a row")
    context_package = None
    interaction_decision = None
    if turn_role == "user":
        context_package = resolve_conversation_context_package(
            db,
            conversation_turn_id=turn.conversation_turn_id,
            organization_id=organization_id,
        )
        if context_package is None:
            raise RuntimeError("conversation context package could not be resolved")
        interaction_decision = resolve_interaction_decision(
            db,
            conversation_turn_id=turn.conversation_turn_id,
            organization_id=organization_id,
        )
        if interaction_decision is None:
            raise RuntimeError("conversation interaction decision could not be resolved")
    if turn_role == "assistant" and assistant_run_uuid is not None:
        repository.mark_assistant_run_completed(
            assistant_run_uuid,
            runtime_metadata={
                "conversation_event_recorded": True,
                "conversation_id": str(turn.conversation_id),
                "conversation_turn_id": str(turn.conversation_turn_id),
            },
        )
    db.commit()
    payload = {
        "conversation_turn_runtime_schema_version": "1",
        "conversation_turn_runtime_prepared": True,
        "conversation_turn_gateway": gateway,
        "conversation_turn": conversation_turn_to_dict(turn),
        "conversation_context": conversation_context_package_to_dict(context_package)
        if context_package is not None
        else None,
        "interaction_decision": interaction_decision_to_dict(interaction_decision)
        if interaction_decision is not None
        else None,
        "conversation_id": str(turn.conversation_id),
        "conversation_turn_id": str(turn.conversation_turn_id),
        "assistant_run_id": str(turn.assistant_run_id) if turn.assistant_run_id else None,
        "assistant_runtime_trace_available": bool(turn.assistant_run_id),
        "conversation_turn_created": turn_created,
        "idempotent_replay": not turn_created if normalized_request_id or deterministic_plan_id else False,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        payload["runtime_persistence"] = _persist_snapshot(
            db, execution_id=f"conversation-turn:{turn.conversation_turn_id}", payload=payload
        )
    return payload


def read_conversation_turn(
    db: Session,
    conversation_turn_id: str,
    *,
    organization_id: uuid.UUID,
) -> dict[str, Any] | None:
    try:
        turn_uuid = uuid.UUID(str(conversation_turn_id))
    except (TypeError, ValueError):
        return None
    record = db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.conversation_turn_id == turn_uuid,
            ConversationTurn.organization_id == organization_id,
            ConversationTurn.ownership_scope == "organization",
        )
    )
    return conversation_turn_to_dict(record) if record is not None else None


def list_conversation_turns_runtime(
    db: Session, *, conversation_id: str, organization_id: uuid.UUID, limit: int = 100
) -> dict[str, Any] | None:
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    if repository.get_scoped_conversation(conversation_uuid, organization_id=organization_id) is None:
        return None
    records = repository.list_conversation_turns(conversation_uuid, limit=limit)
    return {
        "conversation_turn_runtime_schema_version": "1",
        "conversation_turn_runtime_prepared": True,
        "conversation_id": str(conversation_uuid),
        "turns": [conversation_turn_to_dict(record) for record in records],
        "count": len(records),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }


def attach_assistant_response_to_conversation_runtime(
    db: Session,
    *,
    conversation_id: str,
    assistant_response_id: str,
    turn_metadata: dict[str, Any] | None = None,
    organization_id: uuid.UUID,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    gateway = validate_assistant_response_attachment(
        db, conversation_id=conversation_id, assistant_response_id=assistant_response_id
    )
    if gateway.get("blocking_issues"):
        return {
            "conversation_response_runtime_schema_version": "1",
            "conversation_response_runtime_prepared": False,
            "conversation_response_gateway": gateway,
            "conversation_turn_created": False,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "postgresql_source_of_truth": True,
            "llm_used": False,
            "embeddings_used": False,
            "provider_called": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    conversation_uuid = uuid.UUID(str(conversation_id))
    response_uuid = uuid.UUID(str(assistant_response_id))
    repository = AssistantRepository(db)
    if (
        _lock_scoped_conversation_for_turn_write(
            db,
            conversation_id=conversation_uuid,
            organization_id=organization_id,
        )
        is None
    ):
        return None
    existing = repository.find_conversation_turn_by_assistant_response(
        conversation_id=conversation_uuid, assistant_response_id=response_uuid
    )
    try:
        with db.begin_nested():
            turn = repository.attach_assistant_response_turn(
                conversation_id=conversation_uuid,
                assistant_response_id=response_uuid,
                turn_metadata=turn_metadata,
            )
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != ASSISTANT_RESPONSE_TURN_IDENTITY_CONSTRAINT:
            raise
        turn = repository.find_conversation_turn_for_assistant_response(response_uuid)
        if turn is None:
            raise
        if turn.conversation_id == conversation_uuid:
            turn = repository.attach_assistant_response_turn(
                conversation_id=conversation_uuid,
                assistant_response_id=response_uuid,
                turn_metadata=turn_metadata,
            )
        else:
            turn = None
        existing = turn
    except ValueError as exc:
        if str(exc) != "assistant response is already attached to another conversation":
            raise
        turn = None
    if turn is None:
        db.rollback()
        return {
            "conversation_response_runtime_schema_version": "1",
            "conversation_response_runtime_prepared": False,
            "conversation_turn_created": False,
            "passed": False,
            "blocking_issues": [
                {
                    "code": "assistant_response_conversation_conflict",
                    "severity": "blocking",
                    "component": "conversation_response_runtime",
                    "item_id": str(response_uuid),
                    "message": "Assistant response is already attached to another conversation.",
                }
            ],
            "warnings": [],
        }
    if turn.assistant_run_id is not None:
        repository.mark_assistant_run_completed(
            turn.assistant_run_id,
            runtime_metadata={
                "conversation_event_recorded": True,
                "conversation_id": str(turn.conversation_id),
                "conversation_turn_id": str(turn.conversation_turn_id),
                "assistant_response_id": str(turn.assistant_response_id) if turn.assistant_response_id else None,
            },
        )
    db.commit()
    payload = {
        "conversation_response_runtime_schema_version": "1",
        "conversation_response_runtime_prepared": True,
        "conversation_response_gateway": gateway,
        "conversation_turn": conversation_turn_to_dict(turn),
        "conversation_id": str(turn.conversation_id),
        "conversation_turn_id": str(turn.conversation_turn_id),
        "assistant_run_id": str(turn.assistant_run_id) if turn.assistant_run_id else None,
        "assistant_runtime_trace_available": bool(turn.assistant_run_id),
        "assistant_response_id": str(turn.assistant_response_id) if turn.assistant_response_id else None,
        "citation_summary": turn.citation_summary or {},
        "ordered_citations": list(turn.ordered_citations or []),
        "conversation_turn_created": existing is None,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        payload["runtime_persistence"] = _persist_snapshot(
            db, execution_id=f"conversation-response:{turn.conversation_turn_id}", payload=payload
        )
    return payload
