"""Authoritative Conversation Context evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationContextPackage, ConversationTurn
from app.repositories.assistant import AssistantRepository

CONVERSATION_CONTEXT_POLICY_VERSION = "conversation-context.v1"
DEFAULT_MAX_PRIOR_TURNS = 20
_CONTEXT_ELIGIBLE_ROLES = ("user", "assistant", "system", "tool")
_CONTEXT_ELIGIBLE_STATUSES = ("recorded", "completed")


def _turn_content(turn: ConversationTurn) -> str:
    if turn.turn_role in {"assistant", "tool"}:
        return str(turn.output_text or turn.input_text or "").strip()
    return str(turn.input_text or turn.output_text or "").strip()


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def conversation_context_package_to_dict(record: ConversationContextPackage) -> dict[str, Any]:
    return {
        "conversation_context_schema_version": "1",
        "conversation_context_package_id": str(record.conversation_context_package_id),
        "organization_id": str(record.organization_id),
        "ownership_scope": record.ownership_scope,
        "data_origin": record.data_origin,
        "conversation_id": str(record.conversation_id),
        "conversation_turn_id": str(record.conversation_turn_id),
        "current_user_message": record.current_user_message,
        "included_turn_ids": list(record.included_turn_ids or []),
        "excluded_turns": list(record.excluded_turns or []),
        "context_window_policy": dict(record.context_window_policy or {}),
        "context_policy_version": record.context_policy_version,
        "context_hash": record.context_hash,
        "retrieval_inputs": dict(record.retrieval_inputs or {}),
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def resolve_conversation_context_package(
    db: Session,
    *,
    conversation_turn_id: uuid.UUID,
    organization_id: uuid.UUID,
    max_prior_turns: int = DEFAULT_MAX_PRIOR_TURNS,
) -> ConversationContextPackage | None:
    repository = AssistantRepository(db)
    current_turn = repository.get_scoped_conversation_turn(conversation_turn_id, organization_id=organization_id)
    if current_turn is None:
        return None
    if current_turn.turn_role != "user":
        raise ValueError("conversation context can only be resolved for a user turn")
    if current_turn.organization_id != organization_id or current_turn.ownership_scope != "organization":
        raise ValueError("conversation context turn is outside the authorized organization scope")

    existing = repository.get_scoped_conversation_context_package(
        conversation_turn_id=current_turn.conversation_turn_id,
        organization_id=organization_id,
    )
    if existing is not None:
        return existing

    window_size = max(0, int(max_prior_turns))
    prior_turns = repository.list_scoped_conversation_turns_before(
        conversation_id=current_turn.conversation_id,
        conversation_turn_index=current_turn.turn_index,
        organization_id=organization_id,
    )
    eligible: list[tuple[ConversationTurn, str]] = []
    excluded_by_id: dict[str, dict[str, Any]] = {}
    for turn in prior_turns:
        turn_id = str(turn.conversation_turn_id)
        if turn.turn_role not in _CONTEXT_ELIGIBLE_ROLES:
            excluded_by_id[turn_id] = {
                "conversation_turn_id": turn_id,
                "turn_index": int(turn.turn_index),
                "reason": "turn_role_not_context_eligible",
            }
            continue
        if turn.turn_status not in _CONTEXT_ELIGIBLE_STATUSES:
            excluded_by_id[turn_id] = {
                "conversation_turn_id": turn_id,
                "turn_index": int(turn.turn_index),
                "reason": "turn_status_not_context_eligible",
            }
            continue
        content = _turn_content(turn)
        if not content:
            excluded_by_id[turn_id] = {
                "conversation_turn_id": turn_id,
                "turn_index": int(turn.turn_index),
                "reason": "empty_turn_content",
            }
            continue
        eligible.append((turn, content))

    if window_size == 0:
        included: list[tuple[ConversationTurn, str]] = []
        overflow = eligible
    else:
        included = eligible[-window_size:]
        overflow = eligible[:-window_size]
    for turn, _content in overflow:
        turn_id = str(turn.conversation_turn_id)
        excluded_by_id[turn_id] = {
            "conversation_turn_id": turn_id,
            "turn_index": int(turn.turn_index),
            "reason": "context_window_limit",
        }

    included_history = [
        {
            "conversation_turn_id": str(turn.conversation_turn_id),
            "turn_index": int(turn.turn_index),
            "turn_role": turn.turn_role,
            "content": content,
        }
        for turn, content in included
    ]
    excluded_turns = sorted(
        excluded_by_id.values(),
        key=lambda item: (int(item["turn_index"]), str(item["conversation_turn_id"])),
    )
    current_user_message = str(current_turn.input_text or "").strip()
    policy = {
        "max_prior_turns": window_size,
        "eligible_roles": list(_CONTEXT_ELIGIBLE_ROLES),
        "eligible_statuses": list(_CONTEXT_ELIGIBLE_STATUSES),
        "ordering": "turn_index_ascending",
        "selection": "most_recent_eligible",
    }
    retrieval_inputs = {
        "current_user_message": current_user_message,
        "conversation_history": included_history,
    }
    hash_input = {
        "organization_id": str(organization_id),
        "conversation_id": str(current_turn.conversation_id),
        "conversation_turn_id": str(current_turn.conversation_turn_id),
        "context_policy_version": CONVERSATION_CONTEXT_POLICY_VERSION,
        "context_window_policy": policy,
        "current_user_message": current_user_message,
        "included_history": included_history,
        "excluded_turns": excluded_turns,
    }
    return repository.create_conversation_context_package(
        organization_id=organization_id,
        data_origin=current_turn.data_origin,
        conversation_id=current_turn.conversation_id,
        conversation_turn_id=current_turn.conversation_turn_id,
        current_user_message=current_user_message,
        included_turn_ids=[item["conversation_turn_id"] for item in included_history],
        excluded_turns=excluded_turns,
        context_window_policy=policy,
        context_policy_version=CONVERSATION_CONTEXT_POLICY_VERSION,
        context_hash=_canonical_hash(hash_input),
        retrieval_inputs=retrieval_inputs,
    )
