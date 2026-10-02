"""enforce one verification per LLM execution and one turn per response

Revision ID: 20260924_2840
Revises: 20260923_2830
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_2840"
down_revision: str | Sequence[str] | None = "20260923_2830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TURN_INDEX = "uq_ai_conversation_turns_response_identity"
VERIFICATION_INDEX = "uq_ai_assistant_citation_verifications_llm_execution"


def _duplicate(table: str, column: str):
    return (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT {column}, count(*) AS row_count FROM ai.{table} "
                f"WHERE {column} IS NOT NULL GROUP BY {column} "
                f"HAVING count(*) > 1 ORDER BY {column} LIMIT 1"
            )
        )
        .mappings()
        .first()
    )


def _index_definition(name: str):
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'ai' AND indexname = :name"
            ),
            {"name": name},
        )
        .mappings()
        .first()
    )


def _ensure_unique_index(name: str, table: str, column: str, *, partial: bool = False) -> None:
    existing = _index_definition(name)
    if existing is not None:
        definition = existing["indexdef"]
        if not (
            "UNIQUE INDEX" in definition
            and f"ON ai.{table} " in definition
            and f"({column})" in definition
            and (not partial or f"{column} IS NOT NULL" in definition)
        ):
            raise RuntimeError(f"Existing index {name} has an incompatible definition")
        return
    op.create_index(
        name,
        table,
        [column],
        unique=True,
        schema="ai",
        postgresql_where=sa.text(f"{column} IS NOT NULL") if partial else None,
    )


def upgrade() -> None:
    duplicate_turn = _duplicate("conversation_turns", "assistant_response_id")
    if duplicate_turn is not None:
        raise RuntimeError(
            "Cannot enforce assistant response turn identity: response "
            f"{duplicate_turn['assistant_response_id']} has {duplicate_turn['row_count']} historical turns; "
            "resolve through a governed process before upgrading."
        )
    duplicate_verification = _duplicate("assistant_citation_verifications", "llm_execution_id")
    if duplicate_verification is not None:
        raise RuntimeError(
            "Cannot enforce LLM citation identity: execution "
            f"{duplicate_verification['llm_execution_id']} has "
            f"{duplicate_verification['row_count']} historical verifications; "
            "resolve through a governed process before upgrading."
        )
    _ensure_unique_index(TURN_INDEX, "conversation_turns", "assistant_response_id", partial=True)
    _ensure_unique_index(
        VERIFICATION_INDEX, "assistant_citation_verifications", "llm_execution_id"
    )


def downgrade() -> None:
    if _index_definition(VERIFICATION_INDEX) is not None:
        op.drop_index(VERIFICATION_INDEX, table_name="assistant_citation_verifications", schema="ai")
    if _index_definition(TURN_INDEX) is not None:
        op.drop_index(TURN_INDEX, table_name="conversation_turns", schema="ai")
