"""runtime_llm_config: add api_base override (Ollama, etc.)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runtime_llm_config", sa.Column("llm_api_base", sa.Text, nullable=True))
    op.add_column("runtime_llm_config", sa.Column("embedding_api_base", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("runtime_llm_config", "embedding_api_base")
    op.drop_column("runtime_llm_config", "llm_api_base")
