"""Assistant Chat Runtime orchestrator."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationTurn
from app.repositories.assistant import AssistantRepository
from app.services.assistant_citation_verification_runtime import build_assistant_citation_verification_runtime
from app.services.assistant_context_builder_runtime import build_assistant_context_builder_runtime
from app.services.assistant_llm_execution_runtime import build_assistant_llm_execution_runtime
from app.services.assistant_llm_gateway_runtime import build_assistant_llm_gateway_runtime
from app.services.assistant_locale import no_evidence_message
from app.services.assistant_prompt_assembly_runtime import build_assistant_prompt_assembly_runtime
from app.services.assistant_response_runtime import build_assistant_response_runtime
from app.services.assistant_retrieval_execution_runtime import build_assistant_retrieval_execution_readiness_runtime
from app.services.assistant_retrieval_runtime import build_assistant_retrieval_runtime
from app.services.assistant_run_recovery_runtime import (
    attempt_chat_run_takeover,
    initialize_chat_run_claim,
    mark_expired_provider_uncertain,
)
from app.services.assistant_runtime import build_assistant_run_runtime, build_assistant_session_runtime
from app.services.chat_gateway import build_chat_health as build_chat_gateway_health
from app.services.chat_gateway import validate_chat_request
from app.services.conversation_context_runtime import (
    conversation_context_package_to_dict,
    resolve_conversation_context_package,
)
from app.services.conversation_interaction_plan_runtime import (
    interaction_execution_directive_to_dict,
    resolve_interaction_execution_directive,
)
from app.services.conversation_interaction_runtime import (
    interaction_decision_to_dict,
    resolve_interaction_decision,
)
from app.services.conversation_no_search_runtime import (
    ConversationNoSearchExecutionError,
    build_conversation_summary_response_runtime,
    build_persisted_citation_response_runtime,
)
from app.services.conversation_planned_search_runtime import build_planned_conversation_search_runtime
from app.services.conversation_runtime import (
    CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT,
    attach_assistant_response_to_conversation_runtime,
    build_conversation_runtime,
    build_conversation_turn_runtime,
    conversation_to_dict,
    conversation_turn_to_dict,
    find_chat_request_turn,
    list_conversations_runtime,
)


def build_chat_health(db: Session) -> dict[str, Any]:
    return build_chat_gateway_health(db)


def _runtime_persistence(db: Session, *, execution_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.runtime_persistence_runtime import persist_runtime_outputs

    result = persist_runtime_outputs(
        db,
        execution_id=execution_id,
        artifact_id=None,
        runtime_outputs={"chat_runtime": payload},
    )
    return {**result, "runtime_persistence": bool(result.get("persistence_completed"))}


def _failed_payload(
    *, gateway: dict[str, Any], blocking_issues: list[Any], warnings: list[Any] | None = None
) -> dict[str, Any]:
    return {
        "chat_runtime_schema_version": "1",
        "chat_runtime_prepared": False,
        "chat_completed": False,
        "chat_gateway": gateway,
        "conversation_turns_created": 0,
        "assistant_runtime_trace_available": False,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
        "passed": False,
        "blocking_issues": blocking_issues,
        "warnings": warnings or [],
    }


def _issue(code: str, message: str, *, component: str = "chat_runtime") -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "item_id": None,
        "message": message,
    }


def _blocking_from(stage: str, result: dict[str, Any] | None) -> list[Any]:
    if result is None:
        return [
            {
                "code": f"{stage}_not_found",
                "severity": "blocking",
                "component": "chat_runtime",
                "message": f"{stage} returned no result.",
            }
        ]
    return list(result.get("blocking_issues") or [])


def _has_issue_code(issues: list[Any], code: str) -> bool:
    return any(isinstance(issue, dict) and issue.get("code") == code for issue in issues)


def _get_id(result: dict[str, Any], key: str) -> str:
    value = result.get(key)
    if value:
        return str(value)
    raise ValueError(f"{key} missing from runtime result")


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None


def _conversation_title(message: str) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= 96:
        return normalized
    return f"{normalized[:93].rstrip()}…"


def _scoped_search_config(search_config: dict[str, Any], organization_id: Any) -> dict[str, Any]:
    scoped = dict(search_config)
    if not organization_id:
        return scoped
    filters = dict(_dict_value(scoped.get("filters")))
    filters.setdefault("organization_id", str(organization_id))
    scoped["filters"] = filters
    scoped.setdefault("organization_id", str(organization_id))
    return scoped


_OBSERVABILITY_FIELDS = {
    "correlation_id",
    "trace_id",
    "request_id",
    "timestamp",
    "created_at",
    "updated_at",
    "chat_input_fingerprint",
}


def _authoritative_request_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _authoritative_request_value(item)
            for key, item in value.items()
            if key not in _OBSERVABILITY_FIELDS and key != "idempotency_key"
        }
    if isinstance(value, list):
        return [_authoritative_request_value(item) for item in value]
    return value


def _chat_input_fingerprint(
    *,
    message: str,
    requested_by: str | None,
    runtime_context: dict[str, Any] | None,
    runtime_metadata: dict[str, Any] | None,
) -> str:
    authoritative_input = {
        "message": message,
        "requested_by": requested_by,
        "runtime_context": _authoritative_request_value(dict(runtime_context or {})),
        "runtime_metadata": _authoritative_request_value(dict(runtime_metadata or {})),
    }
    encoded = json.dumps(authoritative_input, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _chat_turn_matches_input(turn: ConversationTurn, *, message: str, fingerprint: str) -> bool:
    return turn.input_text == message and (turn.turn_metadata or {}).get("chat_input_fingerprint") == fingerprint


def _top_k(value: Any) -> int:
    try:
        return max(1, min(int(value or 10), 50))
    except (TypeError, ValueError):
        return 10


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _create_initial_idempotent_chat_turn(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    request_id: str,
    message: str,
    requested_by: str | None,
    data_origin: str,
    context: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[Any, Any, bool]:
    repository = AssistantRepository(db)
    conversation = None
    turn = None
    try:
        with db.begin_nested():
            conversation = repository.create_conversation(
                organization_id=organization_id,
                data_origin=data_origin,
                assistant_id=assistant_id,
                conversation_title=_conversation_title(message),
                requested_by=requested_by,
                runtime_context={**context, "chat_runtime_prepared": True},
                conversation_metadata={
                    **metadata,
                    "chat_runtime_prepared": True,
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
            turn = repository.create_conversation_turn(
                organization_id=organization_id,
                data_origin=data_origin,
                conversation_id=conversation.conversation_id,
                assistant_id=assistant_id,
                turn_index=0,
                turn_role="user",
                turn_status="recorded",
                input_text=message,
                turn_metadata={**metadata, "chat_runtime_prepared": True, "chat_turn_role": "user"},
            )
            turn.request_id = request_id
            db.add(turn)
            db.flush()
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
        db.commit()
        return conversation, turn, True
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT:
            raise
        winner = find_chat_request_turn(
            db,
            organization_id=organization_id,
            assistant_id=assistant_id,
            request_id=request_id,
        )
        if winner is None:
            raise
        winner_conversation = repository.get_scoped_conversation(
            winner.conversation_id,
            organization_id=organization_id,
        )
        if winner_conversation is None:
            raise
        db.commit()
        return winner_conversation, winner, False


def _claim_idempotent_chat_execution(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_turn_id: uuid.UUID,
    requested_by: str | None,
    message: str,
    context: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[str, dict[str, Any], bool]:
    repository = AssistantRepository(db)
    user_turn = db.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_turn_id == user_turn_id,
            ConversationTurn.organization_id == organization_id,
            ConversationTurn.assistant_id == assistant_id,
            ConversationTurn.turn_role == "user",
        )
        .with_for_update()
    )
    if user_turn is None:
        raise ValueError("canonical chat user turn not found")

    if user_turn.assistant_run_id is not None:
        run = repository.get_assistant_runtime_run(user_turn.assistant_run_id)
        if run is None:
            raise ValueError("canonical chat assistant run not found")
        if (
            run.organization_id != organization_id
            or run.assistant_id != assistant_id
            or (
                user_turn.assistant_session_id is not None
                and user_turn.assistant_session_id != run.assistant_session_id
            )
        ):
            raise ValueError("canonical chat assistant run lineage is inconsistent")
        session = repository.get_scoped_assistant_session(
            run.assistant_session_id,
            organization_id=organization_id,
        )
        if session is None or session.assistant_id != assistant_id:
            raise ValueError("canonical chat assistant session not found")
        uncertain = False
        takeover_generation = None
        if run.recovery_state == "claimed":
            uncertain = mark_expired_provider_uncertain(
                db,
                run_id=run.assistant_run_id,
                organization_id=organization_id,
                assistant_id=assistant_id,
                assistant_session_id=session.assistant_session_id,
            )
            if not uncertain:
                takeover_generation = attempt_chat_run_takeover(
                    db,
                    run_id=run.assistant_run_id,
                    organization_id=organization_id,
                    assistant_id=assistant_id,
                    assistant_session_id=session.assistant_session_id,
                )
            if uncertain or takeover_generation is not None:
                db.expire(run)
        run_result = {
            "assistant_runtime_schema_version": "1",
            "assistant_runtime_prepared": True,
            "assistant_session_id": str(session.assistant_session_id),
            "assistant_run_id": str(run.assistant_run_id),
            "run_status": run.run_status,
            "recovery_state": run.recovery_state,
            "claim_generation": takeover_generation or run.recovery_generation,
            "recovery_takeover": takeover_generation is not None,
            "provider_outcome_uncertain": uncertain or run.recovery_state == "uncertain",
            "selected_search_mode": run.selected_search_mode,
            "selected_runtime_domain": run.selected_runtime_domain,
            "assistant_session_created": False,
            "assistant_run_created": False,
            "assistant_execution_planned": True,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "idempotent_replay": True,
            "postgresql_source_of_truth": True,
            "passed": True,
            "blocking_issues": [],
            "warnings": [],
        }
        db.commit()
        return str(session.assistant_session_id), run_result, takeover_generation is not None

    conversation = repository.get_scoped_conversation(user_turn.conversation_id, organization_id=organization_id)
    if conversation is None:
        raise ValueError("canonical chat conversation not found")

    session = (
        repository.get_scoped_assistant_session(
            conversation.assistant_session_id,
            organization_id=organization_id,
        )
        if conversation.assistant_session_id is not None
        else None
    )
    session_created = session is None
    if session is None:
        session = repository.create_assistant_session(
            assistant_id=assistant_id,
            execution_organization_id=organization_id,
            session_status="prepared",
            requested_by=requested_by,
            conversation_reference=str(conversation.conversation_id),
            runtime_context={
                **context,
                "conversation_id": str(conversation.conversation_id),
                "chat_runtime_prepared": True,
            },
        )
        repository.attach_conversation_session(
            conversation_id=conversation.conversation_id,
            assistant_session_id=session.assistant_session_id,
            organization_id=organization_id,
        )

    run = repository.create_assistant_runtime_run(
        assistant_id=assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
        requested_query=message,
        selected_search_mode="enterprise_search",
        selected_runtime_domain="enterprise_search",
        runtime_metadata={
            **metadata,
            "conversation_id": str(conversation.conversation_id),
            "chat_runtime_prepared": True,
            "chat_request_execution_claimed": True,
            "assistant_execution_planned": True,
            "assistant_executed": False,
            "llm_used": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "enterprise_search_used": False,
            "hybrid_search_used": False,
            "postgresql_source_of_truth": True,
        },
    )
    claim_generation = initialize_chat_run_claim(db, run)
    user_turn.assistant_session_id = session.assistant_session_id
    user_turn.assistant_run_id = run.assistant_run_id
    user_turn.turn_metadata = {
        **dict(user_turn.turn_metadata or {}),
        "assistant_run_id": str(run.assistant_run_id),
        "chat_request_execution_claimed": True,
    }
    db.add(user_turn)
    db.flush()
    run_result = {
        "assistant_runtime_schema_version": "1",
        "assistant_runtime_prepared": True,
        "assistant_session_id": str(session.assistant_session_id),
        "assistant_run_id": str(run.assistant_run_id),
        "run_status": run.run_status,
        "selected_search_mode": run.selected_search_mode,
        "selected_runtime_domain": run.selected_runtime_domain,
        "assistant_session_created": session_created,
        "assistant_run_created": True,
        "claim_generation": claim_generation,
        "recovery_state": "claimed",
        "recovery_takeover": False,
        "assistant_execution_planned": True,
        "assistant_executed": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "enterprise_search_used": False,
        "hybrid_search_used": False,
        "idempotent_replay": False,
        "postgresql_source_of_truth": True,
        "passed": True,
        "blocking_issues": [],
        "warnings": [],
    }
    db.commit()
    return str(session.assistant_session_id), run_result, True


def _conversation_payload(db: Session, conversation_id: str, *, organization_id: uuid.UUID) -> dict[str, Any] | None:
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (TypeError, ValueError):
        return None
    repository = AssistantRepository(db)
    conversation = repository.get_scoped_conversation(conversation_uuid, organization_id=organization_id)
    if conversation is None:
        return None
    turns = repository.list_conversation_turns(conversation.conversation_id, limit=500)
    responses = []
    for turn in turns:
        if turn.assistant_response_id:
            response = repository.get_assistant_response(turn.assistant_response_id)
            if response is not None:
                responses.append(
                    {
                        "assistant_response_id": str(response.assistant_response_id),
                        "llm_execution_id": str(response.llm_execution_id),
                        "citation_verification_id": str(response.citation_verification_id),
                        "prompt_package_id": str(response.prompt_package_id),
                        "context_package_id": str(response.context_package_id),
                        "assistant_id": str(response.assistant_id),
                        "assistant_session_id": str(response.assistant_session_id)
                        if response.assistant_session_id
                        else None,
                        "response_status": response.response_status,
                        "response_text": response.response_text,
                        "response_format": response.response_format,
                        "citation_summary": {
                            "citation_verification_passed": bool(response.citation_verification_passed),
                            "verified_citation_count": int(response.verified_citation_count or 0),
                            "missing_citation_count": int(response.missing_citation_count or 0),
                            "invalid_citation_count": int(response.invalid_citation_count or 0),
                        },
                        "ordered_citations": list(response.ordered_citations or []),
                    }
                )
    return {
        "chat_runtime_schema_version": "1",
        "chat_runtime_available": True,
        "conversation": conversation_to_dict(conversation),
        "conversation_id": str(conversation.conversation_id),
        "conversation_turns": [conversation_turn_to_dict(turn) for turn in turns],
        "assistant_responses": responses,
        "conversation_metadata": conversation.conversation_metadata or {},
        "runtime_context": conversation.runtime_context or {},
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }


def _persisted_response_lineage(repository: AssistantRepository, turn: ConversationTurn) -> dict[str, str | None]:
    response = (
        repository.get_assistant_response(turn.assistant_response_id)
        if turn.assistant_response_id is not None
        else None
    )
    return {
        "assistant_response_id": str(response.assistant_response_id) if response is not None else None,
        "llm_execution_id": str(response.llm_execution_id) if response is not None else None,
        "citation_verification_id": str(response.citation_verification_id) if response is not None else None,
    }


def build_chat_runtime(
    db: Session,
    *,
    assistant_id: str,
    conversation_id: str | None = None,
    message: str,
    requested_by: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    organization_id: uuid.UUID,
    data_origin: str = "operational",
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    gateway = validate_chat_request(
        db,
        assistant_id=assistant_id,
        conversation_id=conversation_id,
        message=message,
        organization_id=organization_id,
    )
    if gateway.get("blocking_issues"):
        return _failed_payload(
            gateway=gateway,
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=gateway.get("warnings") or [],
        )
    context = {
        **dict(runtime_context or {}),
        "organization_id": str(organization_id),
        "data_origin": data_origin,
    }
    metadata = {
        **dict(runtime_metadata or {}),
        "organization_id": str(organization_id),
        "data_origin": data_origin,
    }
    warnings: list[Any] = list(gateway.get("warnings") or [])
    chain: dict[str, Any] = {}
    conversation_created = False
    conversation_uuid = conversation_id
    repository = AssistantRepository(db)
    assistant_uuid = uuid.UUID(str(assistant_id))
    idempotency_key = str(metadata.get("idempotency_key") or "").strip()
    input_fingerprint = (
        _chat_input_fingerprint(
            message=message,
            requested_by=requested_by,
            runtime_context=runtime_context,
            runtime_metadata=runtime_metadata,
        )
        if idempotency_key
        else None
    )
    if input_fingerprint is not None:
        metadata["chat_input_fingerprint"] = input_fingerprint
    existing_idempotent_turn = None
    canonical_user_turn_id: uuid.UUID | None = None
    if idempotency_key:
        existing_idempotent_turn = find_chat_request_turn(
            db,
            organization_id=organization_id,
            assistant_id=assistant_uuid,
            request_id=idempotency_key,
        )
        if existing_idempotent_turn is not None:
            canonical_user_turn_id = existing_idempotent_turn.conversation_turn_id
            if conversation_uuid and str(existing_idempotent_turn.conversation_id) != str(conversation_uuid):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "idempotency_key_conversation_mismatch",
                            "The request identifier is already associated with another conversation.",
                        )
                    ],
                    warnings=warnings,
                )
            if not _chat_turn_matches_input(
                existing_idempotent_turn, message=message, fingerprint=input_fingerprint or ""
            ):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "idempotency_key_input_mismatch",
                            "The request identifier is already associated with different authoritative input.",
                        )
                    ],
                    warnings=warnings,
                )
            conversation_uuid = str(existing_idempotent_turn.conversation_id)
            persisted_turns = repository.list_conversation_turns(existing_idempotent_turn.conversation_id, limit=500)
            context_package = resolve_conversation_context_package(
                db,
                conversation_turn_id=existing_idempotent_turn.conversation_turn_id,
                organization_id=organization_id,
            )
            if context_package is None:
                raise RuntimeError("conversation context package could not be resolved")
            interaction_decision = resolve_interaction_decision(
                db,
                conversation_turn_id=existing_idempotent_turn.conversation_turn_id,
                organization_id=organization_id,
            )
            if interaction_decision is None:
                raise RuntimeError("conversation interaction decision could not be resolved")
            db.commit()
            chain["conversation_context_runtime"] = conversation_context_package_to_dict(context_package)
            chain["conversation_interaction_runtime"] = interaction_decision_to_dict(interaction_decision)
            completed_turn = next(
                (
                    turn
                    for turn in persisted_turns
                    if turn.turn_index > existing_idempotent_turn.turn_index
                    and turn.turn_role == "assistant"
                    and turn.output_text
                    and (turn.turn_metadata or {}).get("idempotency_key") == idempotency_key
                ),
                None,
            )
            if completed_turn is not None:
                persisted_payload = (
                    _conversation_payload(
                        db,
                        str(existing_idempotent_turn.conversation_id),
                        organization_id=organization_id,
                    )
                    or {}
                )
                return {
                    **persisted_payload,
                    "chat_runtime_prepared": True,
                    "chat_completed": True,
                    "idempotent_replay": True,
                    "response_text": completed_turn.output_text,
                    "ordered_citations": list(completed_turn.ordered_citations or []),
                    **_persisted_response_lineage(repository, completed_turn),
                    "conversation_context": conversation_context_package_to_dict(context_package),
                    "interaction_decision": interaction_decision_to_dict(interaction_decision),
                    "conversation_turns_created": 0,
                    "passed": True,
                    "blocking_issues": [],
                    "warnings": warnings,
                }
    existing_conversation_record = None
    if conversation_uuid:
        try:
            existing_conversation_record = repository.get_scoped_conversation(
                uuid.UUID(str(conversation_uuid)), organization_id=organization_id
            )
        except (TypeError, ValueError):
            existing_conversation_record = None
        persisted_context = (
            _dict_value(existing_conversation_record.runtime_context)
            if existing_conversation_record is not None
            else {}
        )
        persisted_org = persisted_context.get("organization_id")
        requested_org = _first_present(context.get("organization_id"), metadata.get("organization_id"))
        if persisted_org and requested_org and str(persisted_org) != str(requested_org):
            return _failed_payload(
                gateway=gateway,
                blocking_issues=[
                    _issue(
                        "CROSS_ORGANIZATION_ACCESS_DETECTED",
                        "Chat request organization_id differs from the persisted conversation scope.",
                    )
                ],
                warnings=warnings,
            )
        if persisted_org:
            context["organization_id"] = str(persisted_org)
            metadata["organization_id"] = str(persisted_org)
    initial_user_turn_result: dict[str, Any] | None = None
    if not conversation_uuid:
        if idempotency_key:
            conversation_record, initial_user_turn, conversation_created = _create_initial_idempotent_chat_turn(
                db,
                organization_id=organization_id,
                assistant_id=assistant_uuid,
                request_id=idempotency_key,
                message=message,
                requested_by=requested_by,
                data_origin=data_origin,
                context=context,
                metadata=metadata,
            )
            conversation_uuid = str(initial_user_turn.conversation_id)
            existing_conversation_record = conversation_record
            canonical_user_turn_id = initial_user_turn.conversation_turn_id
            if not _chat_turn_matches_input(initial_user_turn, message=message, fingerprint=input_fingerprint or ""):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "idempotency_key_input_mismatch",
                            "The request identifier is already associated with different authoritative input.",
                        )
                    ],
                    warnings=warnings,
                )
            initial_user_turn_result = {
                "conversation_turn": conversation_turn_to_dict(initial_user_turn),
                "conversation_id": str(initial_user_turn.conversation_id),
                "conversation_turn_id": str(initial_user_turn.conversation_turn_id),
                "conversation_turn_created": conversation_created,
                "idempotent_replay": not conversation_created,
                "postgresql_source_of_truth": True,
                "passed": True,
                "blocking_issues": [],
                "warnings": [],
            }
            chain["conversation_runtime"] = {
                "conversation": conversation_to_dict(conversation_record),
                "conversation_id": str(conversation_record.conversation_id),
                "conversation_created": conversation_created,
                "idempotent_replay": not conversation_created,
                "postgresql_source_of_truth": True,
                "passed": True,
                "blocking_issues": [],
                "warnings": [],
            }
        else:
            conversation_result = build_conversation_runtime(
                db,
                organization_id=organization_id,
                data_origin=data_origin,
                assistant_id=assistant_id,
                conversation_title=_conversation_title(message),
                requested_by=requested_by,
                runtime_context={**context, "chat_runtime_prepared": True},
                conversation_metadata={**metadata, "chat_runtime_prepared": True},
            )
            issues = _blocking_from("conversation_runtime", conversation_result)
            if issues:
                return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
            conversation_uuid = _get_id(conversation_result, "conversation_id")
            conversation_created = True
            chain["conversation_runtime"] = conversation_result
    user_turn_created = False
    if initial_user_turn_result is not None:
        user_turn_created = bool(initial_user_turn_result.get("conversation_turn_created"))
        chain["user_conversation_turn"] = initial_user_turn_result
    elif existing_idempotent_turn is None:
        requested_conversation_uuid = str(conversation_uuid)
        user_turn_result = build_conversation_turn_runtime(
            db,
            organization_id=organization_id,
            conversation_id=requested_conversation_uuid,
            turn_role="user",
            input_text=message,
            request_id=idempotency_key or None,
            turn_metadata={**metadata, "chat_runtime_prepared": True, "chat_turn_role": "user"},
        )
        issues = _blocking_from("conversation_turn_runtime", user_turn_result)
        if issues:
            return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
        user_turn_created = bool(user_turn_result.get("conversation_turn_created"))
        if idempotency_key and user_turn_result.get("conversation_turn_id"):
            canonical_user_turn_id = uuid.UUID(str(user_turn_result.get("conversation_turn_id")))
            canonical_turn = repository.get_conversation_turn(canonical_user_turn_id)
            if canonical_turn is None or not _chat_turn_matches_input(
                canonical_turn, message=message, fingerprint=input_fingerprint or ""
            ):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "idempotency_key_input_mismatch",
                            "The request identifier is already associated with different authoritative input.",
                        )
                    ],
                    warnings=warnings,
                )
        persisted_user_conversation_id = str(user_turn_result.get("conversation_id") or requested_conversation_uuid)
        if persisted_user_conversation_id != requested_conversation_uuid:
            conversation_uuid = persisted_user_conversation_id
            conversation_created = False
            existing_conversation_record = repository.get_scoped_conversation(
                uuid.UUID(persisted_user_conversation_id), organization_id=organization_id
            )
        chain["user_conversation_turn"] = user_turn_result
    else:
        canonical_user_turn_id = existing_idempotent_turn.conversation_turn_id
        chain["user_conversation_turn"] = {
            "conversation_turn": conversation_turn_to_dict(existing_idempotent_turn),
            "conversation_turn_created": False,
            "idempotent_replay": True,
        }
    if canonical_user_turn_id is None:
        user_turn_payload = chain.get("user_conversation_turn") or {}
        raw_user_turn_id = user_turn_payload.get("conversation_turn_id")
        if raw_user_turn_id:
            canonical_user_turn_id = uuid.UUID(str(raw_user_turn_id))
    if canonical_user_turn_id is None:
        raise RuntimeError("canonical chat user turn is unavailable")
    context_package = resolve_conversation_context_package(
        db,
        conversation_turn_id=canonical_user_turn_id,
        organization_id=organization_id,
    )
    if context_package is None:
        raise RuntimeError("conversation context package could not be resolved")
    interaction_decision = resolve_interaction_decision(
        db,
        conversation_turn_id=canonical_user_turn_id,
        organization_id=organization_id,
    )
    if interaction_decision is None:
        raise RuntimeError("conversation interaction decision could not be resolved")
    db.commit()
    chain["conversation_context_runtime"] = conversation_context_package_to_dict(context_package)
    chain["conversation_interaction_runtime"] = interaction_decision_to_dict(interaction_decision)
    execution_directive = resolve_interaction_execution_directive(
        db,
        organization_id=organization_id,
        conversation_turn_id=canonical_user_turn_id,
    )
    directive_payload = interaction_execution_directive_to_dict(execution_directive)
    chain["conversation_interaction_plan_runtime"] = directive_payload

    conversation_record = existing_conversation_record or repository.get_conversation(uuid.UUID(str(conversation_uuid)))
    if conversation_record is not None and conversation_record.organization_id != organization_id:
        return _failed_payload(
            gateway=gateway,
            blocking_issues=[
                _issue("conversation_not_authorized", "Conversation is not available in this organization scope.")
            ],
            warnings=warnings,
        )
    if conversation_record is not None and not conversation_record.conversation_title:
        repository.set_conversation_title_if_empty(conversation_record.conversation_id, _conversation_title(message))
        repository.session.commit()
    persisted_context = _dict_value(conversation_record.runtime_context) if conversation_record is not None else {}
    scoped_organization_id = _first_present(
        persisted_context.get("organization_id"),
        context.get("organization_id"),
        metadata.get("organization_id"),
    )
    if scoped_organization_id:
        context.setdefault("organization_id", str(scoped_organization_id))
        metadata.setdefault("organization_id", str(scoped_organization_id))

    execution_metadata = {
        **metadata,
        "interaction_plan_id": str(execution_directive.interaction_plan_id),
        "conversation_turn_id": str(canonical_user_turn_id),
        "planned_action": execution_directive.planned_action,
        "enterprise_search_required": execution_directive.enterprise_search_required,
    }
    if not execution_directive.enterprise_search_required:
        if execution_directive.planned_action == "reuse_persisted_citations":
            try:
                no_search_result = build_persisted_citation_response_runtime(
                    db,
                    organization_id=organization_id,
                    conversation_turn_id=canonical_user_turn_id,
                )
            except ConversationNoSearchExecutionError as exc:
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[_issue("conversation_no_search_execution_failed", str(exc))],
                    warnings=warnings,
                )
            chain["conversation_no_search_runtime"] = no_search_result
            citation_summary = {
                "citation_verification_passed": True,
                "verified_citation_count": int(no_search_result.get("citation_count") or 0),
                "missing_citation_count": 0,
                "invalid_citation_count": 0,
            }
            assistant_turn_result = build_conversation_turn_runtime(
                db,
                organization_id=organization_id,
                conversation_id=str(conversation_uuid),
                turn_role="assistant",
                deterministic_interaction_plan_id=str(execution_directive.interaction_plan_id),
                output_text=str(no_search_result.get("response_text") or ""),
                response_format=str(no_search_result.get("response_format") or "markdown"),
                citation_summary=citation_summary,
                ordered_citations=list(no_search_result.get("ordered_citations") or []),
                turn_metadata={
                    **execution_metadata,
                    "conversation_no_search_runtime": True,
                    "deterministic_response": True,
                },
            )
            issues = _blocking_from("conversation_turn_runtime", assistant_turn_result)
            if issues:
                return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
            chain["assistant_conversation_turn"] = assistant_turn_result
            payload = {
                "chat_runtime_schema_version": "1",
                "chat_runtime_prepared": True,
                "chat_completed": True,
                "interaction_plan_routed": True,
                "interaction_plan_id": str(execution_directive.interaction_plan_id),
                "planned_action": execution_directive.planned_action,
                "enterprise_search_required": False,
                "enterprise_search_bypassed": True,
                "deterministic_response": True,
                "chat_gateway": gateway,
                "conversation_id": str(conversation_uuid),
                "conversation_created": conversation_created,
                "conversation_turn_id": str(canonical_user_turn_id),
                "assistant_session_id": None,
                "assistant_run_id": None,
                "retrieval_plan_id": None,
                "execution_plan_id": None,
                "search_execution_id": None,
                "context_package_id": None,
                "prompt_package_id": None,
                "gateway_id": None,
                "llm_execution_id": None,
                "citation_verification_id": None,
                "assistant_response_id": None,
                "response_text": no_search_result.get("response_text"),
                "ordered_citations": list(no_search_result.get("ordered_citations") or []),
                "citation_summary": citation_summary,
                "conversation_turns_created": int(user_turn_created)
                + (1 if assistant_turn_result.get("conversation_turn_created") else 0),
                "assistant_runtime_trace_available": False,
                "runtime_chain": chain,
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
                "warnings": warnings,
            }
            if persist_snapshot:
                payload["runtime_persistence"] = _runtime_persistence(
                    db,
                    execution_id=(
                        f"chat-runtime:{conversation_uuid}:interaction-plan:{execution_directive.interaction_plan_id}"
                    ),
                    payload=payload,
                )
            return payload
        if execution_directive.planned_action == "summarize_conversation_evidence":
            try:
                no_search_result = build_conversation_summary_response_runtime(
                    db,
                    organization_id=organization_id,
                    conversation_turn_id=canonical_user_turn_id,
                )
            except ConversationNoSearchExecutionError as exc:
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[_issue("conversation_no_search_execution_failed", str(exc))],
                    warnings=warnings,
                )
            chain["conversation_no_search_runtime"] = no_search_result
            citation_summary = {
                "citation_verification_passed": True,
                "verified_citation_count": len(no_search_result.get("ordered_citations") or []),
                "missing_citation_count": 0,
                "invalid_citation_count": 0,
            }
            assistant_turn_result = build_conversation_turn_runtime(
                db,
                organization_id=organization_id,
                conversation_id=str(conversation_uuid),
                turn_role="assistant",
                deterministic_interaction_plan_id=str(execution_directive.interaction_plan_id),
                output_text=no_search_result["response_text"],
                response_format=no_search_result.get("response_format") or "markdown",
                citation_summary=citation_summary,
                ordered_citations=no_search_result.get("ordered_citations") or [],
                turn_metadata={
                    **execution_metadata,
                    "conversation_no_search_runtime": True,
                    "deterministic_response": True,
                    "conversation_summary": True,
                },
            )
            issues = _blocking_from("conversation_turn_runtime", assistant_turn_result)
            if issues:
                return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
            chain["assistant_conversation_turn"] = assistant_turn_result
            payload = {
                "chat_runtime_schema_version": "1",
                "chat_runtime_prepared": True,
                "chat_completed": True,
                "interaction_plan_routed": True,
                "interaction_plan_id": str(execution_directive.interaction_plan_id),
                "planned_action": "summarize_conversation_evidence",
                "enterprise_search_required": False,
                "enterprise_search_bypassed": True,
                "deterministic_response": True,
                "chat_gateway": gateway,
                "conversation_id": str(conversation_uuid),
                "conversation_created": conversation_created,
                "conversation_turn_id": str(canonical_user_turn_id),
                "assistant_session_id": None,
                "assistant_run_id": None,
                "retrieval_plan_id": None,
                "execution_plan_id": None,
                "search_execution_id": None,
                "context_package_id": None,
                "prompt_package_id": None,
                "gateway_id": None,
                "llm_execution_id": None,
                "citation_verification_id": None,
                "assistant_response_id": None,
                "response_text": no_search_result.get("response_text"),
                "ordered_citations": list(no_search_result.get("ordered_citations") or []),
                "citation_summary": citation_summary,
                "conversation_turns_created": int(user_turn_created)
                + (1 if assistant_turn_result.get("conversation_turn_created") else 0),
                "assistant_runtime_trace_available": False,
                "runtime_chain": chain,
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
                "warnings": warnings,
            }
            if persist_snapshot:
                payload["runtime_persistence"] = _runtime_persistence(
                    db,
                    execution_id=(
                        f"chat-runtime:{conversation_uuid}:interaction-plan:{execution_directive.interaction_plan_id}"
                    ),
                    payload=payload,
                )
            return payload
        payload = {
            "chat_runtime_schema_version": "1",
            "chat_runtime_prepared": True,
            "chat_completed": False,
            "interaction_plan_routed": True,
            "interaction_plan_id": str(execution_directive.interaction_plan_id),
            "planned_action": execution_directive.planned_action,
            "enterprise_search_required": False,
            "enterprise_search_bypassed": True,
            "chat_gateway": gateway,
            "conversation_id": str(conversation_uuid),
            "conversation_created": conversation_created,
            "conversation_turn_id": str(canonical_user_turn_id),
            "assistant_session_id": None,
            "assistant_run_id": None,
            "retrieval_plan_id": None,
            "execution_plan_id": None,
            "search_execution_id": None,
            "conversation_turns_created": int(user_turn_created),
            "assistant_runtime_trace_available": False,
            "runtime_chain": chain,
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
            "warnings": warnings,
        }
        if persist_snapshot:
            payload["runtime_persistence"] = _runtime_persistence(
                db,
                execution_id=(
                    f"chat-runtime:{conversation_uuid}:interaction-plan:{execution_directive.interaction_plan_id}"
                ),
                payload=payload,
            )
        return payload

    execution_claimed = True
    claim_generation: int | None = None
    recovery_takeover = False
    assistant_session_id: str | None = None
    if idempotency_key and canonical_user_turn_id is not None:
        try:
            assistant_session_id, run_result, execution_claimed = _claim_idempotent_chat_execution(
                db,
                organization_id=organization_id,
                assistant_id=assistant_uuid,
                user_turn_id=canonical_user_turn_id,
                requested_by=requested_by,
                message=message,
                context=context,
                metadata=execution_metadata,
            )
        except ValueError as exc:
            return _failed_payload(
                gateway=gateway,
                blocking_issues=[_issue("chat_execution_claim_failed", str(exc))],
                warnings=warnings,
            )
        chain["assistant_runtime"] = run_result
        assistant_run_id = _get_id(run_result, "assistant_run_id")
        claim_generation = run_result.get("claim_generation")
        recovery_takeover = bool(run_result.get("recovery_takeover"))
        if not execution_claimed or recovery_takeover:
            persisted_payload = _conversation_payload(db, str(conversation_uuid), organization_id=organization_id) or {}
            persisted_turns = repository.list_conversation_turns(uuid.UUID(str(conversation_uuid)), limit=500)
            completed_turn = next(
                (
                    turn
                    for turn in persisted_turns
                    if turn.turn_role == "assistant"
                    and turn.output_text
                    and (turn.turn_metadata or {}).get("idempotency_key") == idempotency_key
                    and turn.assistant_run_id == uuid.UUID(assistant_run_id)
                    and turn.organization_id == organization_id
                    and turn.assistant_id == assistant_uuid
                    and turn.assistant_session_id == uuid.UUID(assistant_session_id)
                ),
                None,
            )
            if completed_turn is not None:
                repository.mark_assistant_run_completed(uuid.UUID(assistant_run_id))
                db.commit()
                return {
                    **persisted_payload,
                    "chat_runtime_prepared": True,
                    "chat_completed": True,
                    "idempotent_replay": True,
                    "response_text": completed_turn.output_text,
                    "ordered_citations": list(completed_turn.ordered_citations or []),
                    **_persisted_response_lineage(repository, completed_turn),
                    "conversation_turns_created": 0,
                    "assistant_session_id": assistant_session_id,
                    "assistant_run_id": assistant_run_id,
                    "passed": True,
                    "blocking_issues": [],
                    "warnings": warnings,
                }
            verifications = repository.list_scoped_citation_verifications_for_run(
                assistant_run_id=uuid.UUID(assistant_run_id),
                organization_id=organization_id,
                assistant_id=assistant_uuid,
                assistant_session_id=uuid.UUID(assistant_session_id),
            )
            if len(verifications) > 1:
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "assistant_citation_run_ambiguous",
                            "Assistant run has multiple persisted citation verifications.",
                        )
                    ],
                    warnings=warnings,
                )
            recovery_metadata = {
                **execution_metadata,
                "conversation_id": str(conversation_uuid),
                "assistant_run_id": assistant_run_id,
                "chat_runtime_prepared": True,
            }
            if not verifications:
                executions = repository.list_scoped_llm_executions_for_run(
                    assistant_run_id=uuid.UUID(assistant_run_id),
                    conversation_id=uuid.UUID(str(conversation_uuid)),
                    organization_id=organization_id,
                    assistant_id=assistant_uuid,
                    assistant_session_id=uuid.UUID(assistant_session_id),
                )
                if len(executions) > 1:
                    return _failed_payload(
                        gateway=gateway,
                        blocking_issues=[
                            _issue(
                                "assistant_llm_run_ambiguous",
                                "Assistant run has multiple persisted LLM executions.",
                            )
                        ],
                        warnings=warnings,
                    )
                if executions and executions[0].execution_status == "prepared" and recovery_takeover:
                    resumed_execution = build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(executions[0].gateway_id),
                        organization_id=organization_id,
                        request_payload_metadata=recovery_metadata,
                        runtime_run_claim_generation=claim_generation,
                        resume_prepared_claim=True,
                    )
                    issues = _blocking_from("assistant_llm_claim_recovery", resumed_execution)
                    if issues:
                        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
                    executions = repository.list_scoped_llm_executions_for_run(
                        assistant_run_id=uuid.UUID(assistant_run_id),
                        conversation_id=uuid.UUID(str(conversation_uuid)),
                        organization_id=organization_id,
                        assistant_id=assistant_uuid,
                        assistant_session_id=uuid.UUID(assistant_session_id),
                    )
                if executions and executions[0].execution_status == "completed":
                    recovered_citation = build_assistant_citation_verification_runtime(
                        db,
                        llm_execution_id=str(executions[0].llm_execution_id),
                        organization_id=organization_id,
                        request_metadata=recovery_metadata,
                    )
                    issues = _blocking_from("assistant_citation_recovery", recovered_citation)
                    if issues:
                        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
                    verifications = repository.list_scoped_citation_verifications_for_run(
                        assistant_run_id=uuid.UUID(assistant_run_id),
                        organization_id=organization_id,
                        assistant_id=assistant_uuid,
                        assistant_session_id=uuid.UUID(assistant_session_id),
                    )
                    if len(verifications) != 1:
                        raise RuntimeError("recovered citation verification is unavailable or ambiguous")
            responses = repository.list_scoped_assistant_responses_for_run(
                assistant_run_id=uuid.UUID(assistant_run_id),
                organization_id=organization_id,
                assistant_id=assistant_uuid,
                assistant_session_id=uuid.UUID(assistant_session_id),
            )
            if len(responses) > 1:
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue("assistant_response_run_ambiguous", "Assistant run has multiple persisted responses.")
                    ],
                    warnings=warnings,
                )
            response = responses[0] if responses else None
            if response is not None and (
                not verifications or response.citation_verification_id != verifications[0].citation_verification_id
            ):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "assistant_response_run_lineage_conflict",
                            "Persisted response does not match the assistant run citation evidence.",
                        )
                    ],
                    warnings=warnings,
                )
            if response is None and verifications:
                recovered = build_assistant_response_runtime(
                    db,
                    citation_verification_id=str(verifications[0].citation_verification_id),
                    organization_id=organization_id,
                    response_metadata=recovery_metadata,
                )
                issues = _blocking_from("assistant_response_recovery", recovered)
                if issues:
                    return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
                response = repository.get_assistant_response(uuid.UUID(_get_id(recovered, "assistant_response_id")))
            if response is not None:
                attachment = attach_assistant_response_to_conversation_runtime(
                    db,
                    organization_id=organization_id,
                    conversation_id=str(conversation_uuid),
                    assistant_response_id=str(response.assistant_response_id),
                    turn_metadata=execution_metadata,
                )
                issues = _blocking_from("conversation_response_recovery", attachment)
                if issues:
                    return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
                recovered_turn = repository.get_conversation_turn(
                    uuid.UUID(_get_id(attachment, "conversation_turn_id"))
                )
                if recovered_turn is None:
                    raise RuntimeError("recovered assistant conversation turn is unavailable")
                recovered_payload = (
                    _conversation_payload(db, str(conversation_uuid), organization_id=organization_id) or {}
                )
                return {
                    **recovered_payload,
                    "chat_runtime_prepared": True,
                    "chat_completed": True,
                    "idempotent_replay": True,
                    "response_text": recovered_turn.output_text,
                    "ordered_citations": list(recovered_turn.ordered_citations or []),
                    **_persisted_response_lineage(repository, recovered_turn),
                    "conversation_turns_created": 0,
                    "assistant_session_id": assistant_session_id,
                    "assistant_run_id": assistant_run_id,
                    "passed": True,
                    "blocking_issues": [],
                    "warnings": warnings,
                }
            if run_result.get("provider_outcome_uncertain"):
                return _failed_payload(
                    gateway=gateway,
                    blocking_issues=[
                        _issue(
                            "runtime_run_provider_outcome_uncertain",
                            "Provider call has no persisted outcome; manual review is required.",
                        )
                    ],
                    warnings=warnings,
                )
            if recovery_takeover and not verifications and not executions:
                # The abandoned claim had no provider attempt; the fenced owner
                # may rebuild the pre-provider pipeline.
                pass
            else:
                return {
                    **persisted_payload,
                    "chat_runtime_prepared": True,
                    "chat_completed": False,
                    "assistant_execution_in_progress": True,
                    "idempotent_replay": True,
                    "conversation_turns_created": 0,
                    "assistant_session_id": assistant_session_id,
                    "assistant_run_id": assistant_run_id,
                    "assistant_runtime_trace_available": True,
                    "runtime_chain": chain,
                    "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
                    "passed": True,
                    "blocking_issues": [],
                    "warnings": warnings,
                }
    else:
        assistant_session_id = (
            str(conversation_record.assistant_session_id)
            if conversation_record is not None and conversation_record.assistant_session_id
            else None
        )
        if not assistant_session_id:
            session_result = build_assistant_session_runtime(
                db,
                assistant_id=assistant_id,
                organization_id=organization_id,
                requested_by=requested_by,
                conversation_reference=str(conversation_uuid),
                runtime_context={
                    **context,
                    **execution_metadata,
                    "conversation_id": str(conversation_uuid),
                    "chat_runtime_prepared": True,
                },
            )
            issues = _blocking_from("assistant_session_runtime", session_result)
            if issues:
                return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
            assistant_session_id = _get_id(session_result, "assistant_session_id")
            if conversation_record is not None:
                repository.attach_conversation_session(
                    conversation_id=conversation_record.conversation_id,
                    assistant_session_id=uuid.UUID(assistant_session_id),
                    organization_id=organization_id,
                )
                repository.session.commit()
            chain["assistant_session"] = session_result
        run_result = build_assistant_run_runtime(
            db,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            organization_id=organization_id,
            requested_query=message,
            selected_search_mode="enterprise_search",
            selected_runtime_domain="enterprise_search",
            runtime_metadata={
                **execution_metadata,
                "conversation_id": str(conversation_uuid),
                "chat_runtime_prepared": True,
            },
        )
        issues = _blocking_from("assistant_runtime", run_result)
        if issues:
            return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
        assistant_run_id = _get_id(run_result, "assistant_run_id")
        chain["assistant_runtime"] = run_result

    trace_metadata = {
        **execution_metadata,
        "conversation_id": str(conversation_uuid),
        "assistant_run_id": assistant_run_id,
        "chat_runtime_prepared": True,
    }
    retrieval_result = build_assistant_retrieval_runtime(
        db,
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
        organization_id=organization_id,
        requested_query=message,
        selected_search_mode="enterprise_search",
        runtime_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_retrieval_runtime", retrieval_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    retrieval_plan_id = _get_id(retrieval_result, "retrieval_plan_id")
    chain["assistant_retrieval_runtime"] = retrieval_result
    readiness_result = build_assistant_retrieval_execution_readiness_runtime(
        db,
        retrieval_plan_id=retrieval_plan_id,
        organization_id=organization_id,
        readiness_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_retrieval_execution_readiness", readiness_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    execution_plan_id = _get_id(readiness_result, "execution_plan_id")
    chain["assistant_retrieval_execution_readiness"] = readiness_result
    search_result = build_planned_conversation_search_runtime(
        db,
        organization_id=organization_id,
        conversation_turn_id=canonical_user_turn_id,
        execution_plan_id=execution_plan_id,
        top_k=_top_k(context.get("top_k")),
        search_config=_scoped_search_config(
            {"chat_runtime_prepared": True, **_dict_value(context.get("search_config"))},
            trace_metadata.get("organization_id"),
        ),
    )
    issues = _blocking_from("assistant_search_execution", search_result)
    if issues:
        if _has_issue_code(issues, "search_results_empty") and search_result is not None:
            search_execution_id = search_result.get("search_execution_id")
            chain["assistant_search_execution"] = search_result
            no_evidence_text = no_evidence_message(metadata.get("locale") or context.get("locale"))
            citation_summary = {
                "citation_verification_passed": False,
                "verified_citation_count": 0,
                "missing_citation_count": 0,
                "invalid_citation_count": 0,
            }
            assistant_turn_result = build_conversation_turn_runtime(
                db,
                organization_id=organization_id,
                conversation_id=str(conversation_uuid),
                turn_role="assistant",
                deterministic_interaction_plan_id=str(execution_directive.interaction_plan_id),
                output_text=no_evidence_text,
                assistant_run_id=assistant_run_id,
                response_format="markdown",
                citation_summary=citation_summary,
                ordered_citations=[],
                turn_metadata={
                    **trace_metadata,
                    "interaction_plan_id": str(execution_directive.interaction_plan_id),
                    "conversation_turn_id": str(canonical_user_turn_id),
                    "planned_action": execution_directive.planned_action,
                    "no_evidence_response": True,
                    "search_results_empty": True,
                },
            )
            turn_issues = _blocking_from("conversation_turn_runtime", assistant_turn_result)
            if turn_issues:
                return _failed_payload(gateway=gateway, blocking_issues=turn_issues, warnings=warnings + issues)
            chain["assistant_conversation_turn"] = assistant_turn_result
            payload = {
                "chat_runtime_schema_version": "1",
                "chat_runtime_prepared": True,
                "chat_completed": True,
                "no_evidence_response": True,
                "chat_gateway": gateway,
                "conversation_id": str(conversation_uuid),
                "conversation_created": conversation_created,
                "assistant_session_id": assistant_session_id,
                "assistant_run_id": assistant_run_id,
                "retrieval_plan_id": retrieval_plan_id,
                "execution_plan_id": execution_plan_id,
                "search_execution_id": str(search_execution_id) if search_execution_id else None,
                "context_package_id": None,
                "prompt_package_id": None,
                "gateway_id": None,
                "llm_execution_id": None,
                "citation_verification_id": None,
                "assistant_response_id": None,
                "response_text": no_evidence_text,
                "ordered_citations": [],
                "citation_summary": citation_summary,
                "conversation_turns_created": int(user_turn_created)
                + (1 if assistant_turn_result.get("conversation_turn_created") else 0),
                "assistant_runtime_trace_available": bool(
                    assistant_run_id and assistant_turn_result.get("assistant_runtime_trace_available")
                ),
                "runtime_chain": chain,
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
                "warnings": warnings + issues,
            }
            if persist_snapshot:
                payload["runtime_persistence"] = _runtime_persistence(
                    db,
                    execution_id=f"chat-runtime:{conversation_uuid}:no-evidence:{assistant_run_id}",
                    payload=payload,
                )
            return payload
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    search_execution_id = _get_id(search_result, "search_execution_id")
    chain["assistant_search_execution"] = search_result
    context_result = build_assistant_context_builder_runtime(
        db,
        search_execution_id=search_execution_id,
        organization_id=organization_id,
        package_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_context_builder", context_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    context_package_id = _get_id(context_result, "context_package_id")
    chain["assistant_context_builder"] = context_result
    prompt_result = build_assistant_prompt_assembly_runtime(
        db,
        context_package_id=context_package_id,
        organization_id=organization_id,
        prompt_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_prompt_assembly", prompt_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    prompt_package_id = _get_id(prompt_result, "prompt_package_id")
    chain["assistant_prompt_assembly"] = prompt_result
    llm_gateway_result = build_assistant_llm_gateway_runtime(
        db,
        prompt_package_id=prompt_package_id,
        organization_id=organization_id,
        gateway_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_llm_gateway", llm_gateway_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    gateway_id = _get_id(llm_gateway_result, "gateway_id")
    chain["assistant_llm_gateway"] = llm_gateway_result
    llm_execution_result = build_assistant_llm_execution_runtime(
        db,
        gateway_id=gateway_id,
        organization_id=organization_id,
        request_payload_metadata=trace_metadata,
        runtime_run_claim_generation=claim_generation,
    )
    issues = _blocking_from("assistant_llm_execution", llm_execution_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    llm_execution_id = _get_id(llm_execution_result, "llm_execution_id")
    chain["assistant_llm_execution"] = llm_execution_result
    citation_result = build_assistant_citation_verification_runtime(
        db,
        llm_execution_id=llm_execution_id,
        organization_id=organization_id,
        request_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_citation_verification", citation_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    citation_verification_id = _get_id(citation_result, "citation_verification_id")
    chain["assistant_citation_verification"] = citation_result
    response_result = build_assistant_response_runtime(
        db,
        citation_verification_id=citation_verification_id,
        organization_id=organization_id,
        response_metadata=trace_metadata,
    )
    issues = _blocking_from("assistant_response", response_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    assistant_response_id = _get_id(response_result, "assistant_response_id")
    chain["assistant_response"] = response_result
    assistant_turn_result = attach_assistant_response_to_conversation_runtime(
        db,
        organization_id=organization_id,
        conversation_id=str(conversation_uuid),
        assistant_response_id=assistant_response_id,
        turn_metadata=trace_metadata,
    )
    issues = _blocking_from("conversation_response_runtime", assistant_turn_result)
    if issues:
        return _failed_payload(gateway=gateway, blocking_issues=issues, warnings=warnings)
    chain["assistant_conversation_turn"] = assistant_turn_result
    citation_summary = (
        assistant_turn_result.get("citation_summary")
        or response_result.get("citation_summary")
        or {
            "verified_citation_count": response_result.get("verified_citation_count"),
            "missing_citation_count": response_result.get("missing_citation_count"),
            "invalid_citation_count": response_result.get("invalid_citation_count"),
        }
    )
    payload = {
        "chat_runtime_schema_version": "1",
        "chat_runtime_prepared": True,
        "chat_completed": True,
        "chat_gateway": gateway,
        "conversation_id": str(conversation_uuid),
        "conversation_created": conversation_created,
        "assistant_session_id": assistant_session_id,
        "assistant_run_id": assistant_run_id,
        "retrieval_plan_id": retrieval_plan_id,
        "execution_plan_id": execution_plan_id,
        "search_execution_id": search_execution_id,
        "context_package_id": context_package_id,
        "prompt_package_id": prompt_package_id,
        "gateway_id": gateway_id,
        "llm_execution_id": llm_execution_id,
        "citation_verification_id": citation_verification_id,
        "assistant_response_id": assistant_response_id,
        "response_text": response_result.get("response_text"),
        "ordered_citations": response_result.get("ordered_citations")
        or assistant_turn_result.get("ordered_citations")
        or [],
        "citation_summary": citation_summary,
        "conversation_turns_created": int(user_turn_created)
        + (1 if assistant_turn_result.get("conversation_turn_created") else 0),
        "assistant_runtime_trace_available": bool(
            assistant_run_id and assistant_turn_result.get("assistant_runtime_trace_available")
        ),
        "runtime_chain": chain,
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
        "warnings": warnings,
    }
    if persist_snapshot:
        payload["runtime_persistence"] = _runtime_persistence(
            db, execution_id=f"chat-runtime:{conversation_uuid}:{assistant_response_id}", payload=payload
        )
    return payload


def read_chat_runtime(db: Session, conversation_id: str, *, organization_id: uuid.UUID) -> dict[str, Any] | None:
    return _conversation_payload(db, conversation_id, organization_id=organization_id)


def list_chat_runtime(
    db: Session,
    *,
    assistant_id: str | None = None,
    conversation_status: str | None = None,
    limit: int = 100,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    result = list_conversations_runtime(
        db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        conversation_status=conversation_status,
        limit=limit,
    )
    return {
        "chat_runtime_schema_version": "1",
        "chat_runtime_available": True,
        "conversations": result.get("conversations") or [],
        "count": result.get("count") or 0,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }
