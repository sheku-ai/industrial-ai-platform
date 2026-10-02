"""Assistant Chat Runtime gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository


def _issue(code: str, message: str, *, component: str = "chat_gateway", item_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "severity": "blocking", "component": component, "item_id": item_id, "message": message}


def build_chat_health(db: Session) -> dict[str, Any]:
    repository = AssistantRepository(db)
    return {
        "chat_runtime_available": True,
        "chat_runtime_status": "ready",
        "conversation_runtime_available": True,
        "assistant_runtime_available": True,
        "assistant_count": len(repository.list_assistant_definitions(limit=1)),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }


def validate_chat_request(
    db: Session,
    *,
    assistant_id: str,
    conversation_id: str | None = None,
    message: str | None = None,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    assistant = None
    conversation = None
    assistant_uuid: uuid.UUID | None = None
    conversation_uuid: uuid.UUID | None = None
    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (TypeError, ValueError):
        blocking_issues.append(
            _issue("assistant_id_invalid", "assistant_id must be a valid UUID.", item_id=str(assistant_id))
        )
    if assistant_uuid is not None:
        assistant = repository.get_scoped_assistant_definition(
            assistant_uuid, organization_id=organization_id
        )
        if assistant is None:
            blocking_issues.append(
                _issue("assistant_not_found", "Assistant definition was not found.", item_id=str(assistant_uuid))
            )
        elif assistant.assistant_status not in {"prepared", "active"}:
            blocking_issues.append(
                _issue(
                    "assistant_not_active",
                    "Assistant must be prepared or active before chat execution.",
                    item_id=str(assistant.assistant_id),
                )
            )
    if conversation_id:
        try:
            conversation_uuid = uuid.UUID(str(conversation_id))
        except (TypeError, ValueError):
            blocking_issues.append(
                _issue("conversation_id_invalid", "conversation_id must be a valid UUID.", item_id=str(conversation_id))
            )
        if conversation_uuid is not None:
            conversation = repository.get_scoped_conversation(
                conversation_uuid, organization_id=organization_id
            )
            if conversation is None:
                blocking_issues.append(
                    _issue("conversation_not_found", "Conversation was not found.", item_id=str(conversation_uuid))
                )
            elif (
                assistant_uuid is not None
                and conversation.assistant_id is not None
                and conversation.assistant_id != assistant_uuid
            ):
                blocking_issues.append(
                    _issue(
                        "conversation_assistant_mismatch",
                        "Conversation belongs to a different assistant.",
                        item_id=str(conversation_uuid),
                    )
                )
            elif assistant_uuid is not None and conversation.assistant_session_id is not None:
                session = repository.get_scoped_assistant_session(
                    conversation.assistant_session_id,
                    organization_id=organization_id,
                )
                if session is None:
                    if repository.assistant_session_exists(conversation.assistant_session_id):
                        blocking_issues.append(
                            _issue(
                                "conversation_session_not_authorized_for_organization",
                                "Conversation session is not available in the authorized organization scope.",
                                item_id=str(conversation.assistant_session_id),
                            )
                        )
                    else:
                        blocking_issues.append(
                            _issue(
                                "conversation_session_not_found",
                                "Conversation references an assistant session that was not found.",
                                item_id=str(conversation.assistant_session_id),
                            )
                        )
                elif session.assistant_id != assistant_uuid:
                    blocking_issues.append(
                        _issue(
                            "conversation_session_assistant_mismatch",
                            "Conversation session belongs to a different assistant.",
                            item_id=str(conversation.assistant_session_id),
                        )
                    )
    if not str(message or "").strip():
        blocking_issues.append(_issue("message_empty", "Chat message must not be empty."))
    return {
        "chat_gateway_schema_version": "1",
        "chat_runtime_ready": not blocking_issues,
        "assistant_id": str(assistant_uuid) if assistant_uuid else None,
        "conversation_id": str(conversation_uuid) if conversation_uuid else None,
        "assistant_exists": assistant is not None,
        "conversation_exists": conversation is not None if conversation_id else None,
        "assistant_status": assistant.assistant_status if assistant is not None else None,
        "assistant_active": assistant is not None and assistant.assistant_status in {"prepared", "active"},
        "message_valid": bool(str(message or "").strip()),
        "postgresql_source_of_truth": True,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }
