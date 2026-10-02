from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationTurn
from app.repositories.assistant import AssistantRepository
from app.services import conversation_runtime
from app.services.conversation_runtime import (
    DETERMINISTIC_TURN_IDENTITY_CONSTRAINT,
    _deterministic_turn_fingerprint,
    _validate_deterministic_winner,
    build_conversation_turn_runtime,
)


def _evidence() -> tuple[object, object, object]:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    conversation = SimpleNamespace(
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        conversation_id=conversation_id,
    )
    user = SimpleNamespace(
        conversation_turn_id=user_id,
        organization_id=organization_id,
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        conversation_id=conversation_id,
        turn_role="user",
        input_text="same message",
        turn_metadata={"chat_input_fingerprint": "a" * 64},
    )
    plan = SimpleNamespace(
        interaction_plan_id=plan_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=user_id,
        ownership_scope="organization",
        planned_action="summarize_conversation_evidence",
        enterprise_search_required=False,
        input_hash="b" * 64,
        plan_hash="c" * 64,
    )

    class Db:
        def get(self, model: object, identifier: uuid.UUID) -> object | None:
            if identifier == plan_id:
                return plan
            if identifier == user_id:
                return user
            return None

    return Db(), conversation, plan


def _fingerprint(db: object, conversation: object, plan: object, **changes: object) -> str:
    metadata = {
        "conversation_no_search_runtime": True,
        "interaction_plan_id": str(plan.interaction_plan_id),
        "conversation_turn_id": str(plan.conversation_turn_id),
        "planned_action": plan.planned_action,
    }
    metadata.update(changes.pop("metadata", {}))
    return _deterministic_turn_fingerprint(
        db,
        plan_id=changes.pop("plan_id", plan.interaction_plan_id),
        conversation=conversation,
        organization_id=changes.pop("organization_id", conversation.organization_id),
        turn_role=changes.pop("turn_role", "assistant"),
        turn_metadata=metadata,
    )


def test_equivalent_retry_has_stable_authoritative_fingerprint() -> None:
    db, conversation, plan = _evidence()
    assert _fingerprint(db, conversation, plan) == _fingerprint(db, conversation, plan)


@pytest.mark.parametrize("field", ["input_text", "chat_input_fingerprint", "plan_hash", "input_hash"])
def test_changed_authoritative_input_changes_fingerprint(field: str) -> None:
    db, conversation, plan = _evidence()
    before = _fingerprint(db, conversation, plan)
    target = db.get(None, plan.conversation_turn_id) if field in {"input_text", "chat_input_fingerprint"} else plan
    if field == "chat_input_fingerprint":
        target.turn_metadata = {"chat_input_fingerprint": "z" * 64}
    else:
        setattr(target, field, "changed")
    assert _fingerprint(db, conversation, plan) != before


@pytest.mark.parametrize("field", ["organization_id", "conversation_id", "assistant_id", "assistant_session_id"])
def test_cross_lineage_rejected(field: str) -> None:
    db, conversation, plan = _evidence()
    setattr(conversation, field, uuid.uuid4())
    with pytest.raises(ValueError, match="lineage"):
        _fingerprint(db, conversation, plan)


@pytest.mark.parametrize("field", ["interaction_plan_id", "conversation_turn_id", "planned_action"])
def test_metadata_lineage_mismatch_rejected(field: str) -> None:
    db, conversation, plan = _evidence()
    with pytest.raises(ValueError, match="inconsistent"):
        _fingerprint(db, conversation, plan, metadata={field: str(uuid.uuid4())})


def test_user_and_generative_roles_cannot_claim_deterministic_identity() -> None:
    db, conversation, plan = _evidence()
    with pytest.raises(ValueError, match="lineage"):
        _fingerprint(db, conversation, plan, turn_role="user")


def test_winner_reuse_requires_all_lineage_and_fingerprint() -> None:
    db, conversation, plan = _evidence()
    fingerprint = _fingerprint(db, conversation, plan)
    winner = SimpleNamespace(
        deterministic_interaction_plan_id=plan.interaction_plan_id,
        deterministic_input_fingerprint=fingerprint,
        organization_id=conversation.organization_id,
        conversation_id=conversation.conversation_id,
        assistant_id=conversation.assistant_id,
        assistant_session_id=conversation.assistant_session_id,
        assistant_run_id=None,
        turn_role="assistant",
        assistant_response_id=None,
    )
    _validate_deterministic_winner(
        winner,
        plan_id=plan.interaction_plan_id,
        fingerprint=fingerprint,
        conversation=conversation,
        organization_id=conversation.organization_id,
        assistant_run_id=None,
    )
    winner.deterministic_input_fingerprint = "z" * 64
    with pytest.raises(ValueError, match="conflicts"):
        _validate_deterministic_winner(
            winner,
            plan_id=plan.interaction_plan_id,
            fingerprint=fingerprint,
            conversation=conversation,
            organization_id=conversation.organization_id,
            assistant_run_id=None,
        )


def test_model_identity_is_partial_unique_and_preserves_other_turns() -> None:
    index = next(i for i in ConversationTurn.__table__.indexes if i.name == DETERMINISTIC_TURN_IDENTITY_CONSTRAINT)
    assert index.unique is True
    assert [column.name for column in index.columns] == ["deterministic_interaction_plan_id"]
    assert "IS NOT NULL" in str(index.dialect_options["postgresql"]["where"])
    assert any(i.name == "uq_ai_conversation_turns_response_identity" for i in ConversationTurn.__table__.indexes)
    assert any(c.name == "uq_ai_conversation_turns_conversation_index" for c in ConversationTurn.__table__.constraints)


def test_postgresql_deterministic_identity_schema_and_sql_uniqueness() -> None:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                definition = connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE schemaname='ai' "
                        "AND tablename='conversation_turns' "
                        "AND indexname='uq_ai_conversation_turns_deterministic_operation'"
                    )
                ).scalar_one()
                assert "UNIQUE INDEX" in definition
                assert "deterministic_interaction_plan_id IS NOT NULL" in definition
                constraints = (
                    connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid='ai.conversation_turns'::regclass "
                            "AND (conname='fk_ai_conversation_turns_deterministic_plan_lineage' "
                            "OR conname LIKE 'ck_conversation_turns_ck_ai_conversation_turns_determin%' "
                            "OR conname='uq_ai_conversation_turns_conversation_index')"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(constraints) == 3
                connection.execute(
                    text(
                        "CREATE TEMP TABLE deterministic_probe "
                        "(deterministic_interaction_plan_id uuid, input_text text)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX deterministic_probe_identity ON "
                        "deterministic_probe (deterministic_interaction_plan_id) "
                        "WHERE deterministic_interaction_plan_id IS NOT NULL"
                    )
                )
                plan_a, plan_b = uuid.uuid4(), uuid.uuid4()
                connection.execute(
                    text(
                        "INSERT INTO deterministic_probe (deterministic_interaction_plan_id, input_text) "
                        "VALUES (:plan, 'same text'), (NULL, 'legacy'), (NULL, 'legacy')"
                    ),
                    {"plan": plan_a},
                )
                connection.execute(
                    text(
                        "INSERT INTO deterministic_probe (deterministic_interaction_plan_id, input_text) "
                        "VALUES (:plan, 'same text')"
                    ),
                    {"plan": plan_b},
                )
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO deterministic_probe (deterministic_interaction_plan_id, input_text) "
                            "VALUES (:plan, 'same text')"
                        ),
                        {"plan": plan_a},
                    )
                assert connection.execute(text("SELECT count(*) FROM deterministic_probe")).scalar_one() == 4
                source = (
                    connection.execute(
                        text(
                            "SELECT p.interaction_plan_id, p.organization_id, p.conversation_id, "
                            "c.assistant_id, c.assistant_session_id "
                            "FROM ai.conversation_interaction_plans p "
                            "JOIN ai.conversations c ON c.conversation_id=p.conversation_id "
                            "ORDER BY p.created_at LIMIT 1"
                        )
                    )
                    .mappings()
                    .first()
                )
                if source is not None:
                    next_index = connection.execute(
                        text(
                            "SELECT coalesce(max(turn_index), -1)+1 FROM ai.conversation_turns "
                            "WHERE conversation_id=:conversation_id"
                        ),
                        {"conversation_id": source["conversation_id"]},
                    ).scalar_one()
                    parameters = dict(source)
                    parameters["next_index"] = next_index
                    parameters["turn_id"] = uuid.uuid4()
                    insert = text(
                        "INSERT INTO ai.conversation_turns "
                        "(conversation_turn_id,organization_id,ownership_scope,data_origin,"
                        "conversation_id,assistant_id,assistant_session_id,turn_index,turn_role,"
                        "turn_status,output_text,deterministic_interaction_plan_id,"
                        "deterministic_input_fingerprint) "
                        "VALUES (:turn_id,:organization_id,'organization','validation',"
                        ":conversation_id,:assistant_id,:assistant_session_id,:next_index,"
                        "'assistant','completed','probe',:interaction_plan_id,:fingerprint)"
                    )
                    parameters["fingerprint"] = "f" * 64
                    connection.execute(insert, parameters)
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(
                            insert,
                            {**parameters, "turn_id": uuid.uuid4(), "next_index": next_index + 1},
                        )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_postgresql_runtime_first_retry_conflict_and_new_operation_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                rows = (
                    connection.execute(
                        text(
                            "SELECT p.interaction_plan_id,p.organization_id,p.conversation_id,p.conversation_turn_id "
                            "FROM ai.conversation_interaction_plans p "
                            "JOIN ai.conversation_turns t ON t.conversation_turn_id=p.conversation_turn_id "
                            "WHERE t.turn_role='user' AND t.assistant_id IS NOT NULL "
                            "ORDER BY p.created_at LIMIT 2"
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(rows) < 2:
                    pytest.skip("two persisted interaction plans required for runtime integration")
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    results = []
                    for source in rows:
                        db.execute(
                            text(
                                "UPDATE ai.conversation_interaction_plans "
                                "SET enterprise_search_required=false, "
                                "planned_action='summarize_conversation_evidence' "
                                "WHERE interaction_plan_id=:plan_id"
                            ),
                            {"plan_id": source["interaction_plan_id"]},
                        )
                        db.commit()
                        kwargs = {
                            "organization_id": source["organization_id"],
                            "conversation_id": str(source["conversation_id"]),
                            "turn_role": "assistant",
                            "output_text": "same deterministic text",
                            "deterministic_interaction_plan_id": str(source["interaction_plan_id"]),
                            "turn_metadata": {
                                "conversation_no_search_runtime": True,
                                "interaction_plan_id": str(source["interaction_plan_id"]),
                                "conversation_turn_id": str(source["conversation_turn_id"]),
                                "planned_action": "summarize_conversation_evidence",
                            },
                            "persist_snapshot": False,
                        }
                        first = build_conversation_turn_runtime(db, **kwargs)
                        assert first is not None and first["passed"] and first["conversation_turn_created"]
                        retry = build_conversation_turn_runtime(db, **kwargs)
                        assert retry is not None and retry["passed"]
                        assert retry["idempotent_replay"] is True
                        assert retry["conversation_turn_id"] == first["conversation_turn_id"]
                        results.append(first)
                        assert (
                            db.execute(
                                text(
                                    "SELECT count(*) FROM ai.conversation_turns "
                                    "WHERE deterministic_interaction_plan_id=:plan_id"
                                ),
                                {"plan_id": source["interaction_plan_id"]},
                            ).scalar_one()
                            == 1
                        )
                    assert results[0]["conversation_turn_id"] != results[1]["conversation_turn_id"]
                    # A stale pre-insert read simulates the losing worker. PostgreSQL
                    # rejects the duplicate; the loser must validate and return the winner.
                    source = rows[0]
                    race_kwargs = {
                        "organization_id": source["organization_id"],
                        "conversation_id": str(source["conversation_id"]),
                        "turn_role": "assistant",
                        "output_text": "same deterministic text",
                        "deterministic_interaction_plan_id": str(source["interaction_plan_id"]),
                        "turn_metadata": {
                            "conversation_no_search_runtime": True,
                            "interaction_plan_id": str(source["interaction_plan_id"]),
                            "conversation_turn_id": str(source["conversation_turn_id"]),
                            "planned_action": "summarize_conversation_evidence",
                        },
                        "persist_snapshot": False,
                    }
                    original_find = conversation_runtime._find_deterministic_turn
                    find_count = 0

                    def stale_first_read(session: Session, plan_id: uuid.UUID) -> ConversationTurn | None:
                        nonlocal find_count
                        find_count += 1
                        return None if find_count == 1 else original_find(session, plan_id)

                    with monkeypatch.context() as patch:
                        patch.setattr(conversation_runtime, "_find_deterministic_turn", stale_first_read)
                        loser = build_conversation_turn_runtime(db, **race_kwargs)
                    assert loser is not None and loser["idempotent_replay"]
                    assert loser["conversation_turn_id"] == results[0]["conversation_turn_id"]

                    def unrelated_error(self: AssistantRepository, **kwargs: object) -> ConversationTurn:
                        original = Exception("foreign key failure")
                        original.diag = SimpleNamespace(constraint_name="fk_unrelated")  # type: ignore[attr-defined]
                        raise IntegrityError("insert", {}, original)

                    with monkeypatch.context() as patch:
                        patch.setattr(conversation_runtime, "_find_deterministic_turn", lambda *_: None)
                        patch.setattr(AssistantRepository, "create_conversation_turn", unrelated_error)
                        with pytest.raises(IntegrityError):
                            build_conversation_turn_runtime(db, **race_kwargs)
                    db.execute(
                        text(
                            "UPDATE ai.conversation_interaction_plans SET plan_hash=:hash "
                            "WHERE interaction_plan_id=:plan_id"
                        ),
                        {"plan_id": rows[0]["interaction_plan_id"], "hash": "z" * 64},
                    )
                    db.commit()
                    with pytest.raises(ValueError, match="conflicts"):
                        build_conversation_turn_runtime(
                            db,
                            organization_id=rows[0]["organization_id"],
                            conversation_id=str(rows[0]["conversation_id"]),
                            turn_role="assistant",
                            output_text="same deterministic text",
                            deterministic_interaction_plan_id=str(rows[0]["interaction_plan_id"]),
                            turn_metadata={
                                "conversation_no_search_runtime": True,
                                "interaction_plan_id": str(rows[0]["interaction_plan_id"]),
                                "conversation_turn_id": str(rows[0]["conversation_turn_id"]),
                                "planned_action": "summarize_conversation_evidence",
                            },
                            persist_snapshot=False,
                        )
            finally:
                outer.rollback()
    finally:
        engine.dispose()
