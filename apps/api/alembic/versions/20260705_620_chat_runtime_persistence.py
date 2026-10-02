"""add chat runtime persistence domain

Revision ID: 20260705_620
Revises: 20260705_610
Create Date: 2026-07-05
"""

from alembic import op


revision = "20260705_620"
down_revision = "20260705_610"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


RUNTIME_DOMAINS_WITH_CHAT = (
    "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts',"
    "'embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime',"
    "'assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder',"
    "'assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','assistant_response',"
    "'conversation_runtime','chat_runtime','enterprise_search','runtime_persistence')"
)

RUNTIME_DOMAINS_WITHOUT_CHAT = (
    "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts',"
    "'embedding_runtime','vector_index_runtime','semantic_search_runtime','hybrid_search_runtime','workflow_runtime','assistant_runtime',"
    "'assistant_retrieval_runtime','assistant_retrieval_execution_readiness','assistant_search_execution','assistant_context_builder',"
    "'assistant_prompt_assembly','assistant_llm_gateway','assistant_llm_execution','assistant_citation_verification','assistant_response',"
    "'conversation_runtime','enterprise_search','runtime_persistence')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        RUNTIME_DOMAINS_WITH_CHAT,
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        RUNTIME_DOMAINS_WITHOUT_CHAT,
        schema="runtime",
    )
