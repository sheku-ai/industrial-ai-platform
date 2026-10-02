"""merge runtime migration heads

Revision ID: 20260618_1500
Revises: 0002_knowledge_runtime_data_model, 20260618_1006
Create Date: 2026-06-18
"""

from typing import Sequence, Union

revision: str = "20260618_1500"
down_revision: Union[str, tuple[str, str]] = (
    "0002_knowledge_runtime_data_model",
    "20260618_1006",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
