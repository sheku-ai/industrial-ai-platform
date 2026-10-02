"""add optional runtime execution links to domain jobs"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260619_1906"
down_revision: Union[str, None] = "20260619_1901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("runtime_execution_id", UUID, nullable=True), schema="documents")
    op.create_foreign_key("fk_ingestion_jobs_runtime_execution", "ingestion_jobs", "executions", ["organization_id", "runtime_execution_id"], ["organization_id", "id"], source_schema="documents", referent_schema="runtime")
    op.create_index("uq_ingestion_jobs_runtime_execution", "ingestion_jobs", ["runtime_execution_id"], unique=True, schema="documents", postgresql_where=sa.text("runtime_execution_id IS NOT NULL"))

    op.add_column("indexing_jobs", sa.Column("runtime_execution_id", UUID, nullable=True), schema="documents")
    op.create_foreign_key("fk_indexing_jobs_runtime_execution", "indexing_jobs", "executions", ["organization_id", "runtime_execution_id"], ["organization_id", "id"], source_schema="documents", referent_schema="runtime")
    op.create_index("uq_indexing_jobs_runtime_execution", "indexing_jobs", ["runtime_execution_id"], unique=True, schema="documents", postgresql_where=sa.text("runtime_execution_id IS NOT NULL"))

    op.add_column("connector_runs", sa.Column("runtime_execution_id", UUID, nullable=True), schema="connectors")
    op.create_foreign_key("fk_connector_runs_runtime_execution", "connector_runs", "executions", ["runtime_execution_id"], ["id"], source_schema="connectors", referent_schema="runtime")
    op.create_index("uq_connector_runs_runtime_execution", "connector_runs", ["runtime_execution_id"], unique=True, schema="connectors", postgresql_where=sa.text("runtime_execution_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_connector_runs_runtime_execution", table_name="connector_runs", schema="connectors")
    op.drop_constraint("fk_connector_runs_runtime_execution", "connector_runs", schema="connectors", type_="foreignkey")
    op.drop_column("connector_runs", "runtime_execution_id", schema="connectors")
    op.drop_index("uq_indexing_jobs_runtime_execution", table_name="indexing_jobs", schema="documents")
    op.drop_constraint("fk_indexing_jobs_runtime_execution", "indexing_jobs", schema="documents", type_="foreignkey")
    op.drop_column("indexing_jobs", "runtime_execution_id", schema="documents")
    op.drop_index("uq_ingestion_jobs_runtime_execution", table_name="ingestion_jobs", schema="documents")
    op.drop_constraint("fk_ingestion_jobs_runtime_execution", "ingestion_jobs", schema="documents", type_="foreignkey")
    op.drop_column("ingestion_jobs", "runtime_execution_id", schema="documents")
