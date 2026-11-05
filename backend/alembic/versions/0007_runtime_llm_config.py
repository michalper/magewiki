"""runtime_llm_config: BYOK model/key override, settable via /settings UI

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_llm_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("llm_model", sa.Text, nullable=True),
        sa.Column("llm_api_key", sa.Text, nullable=True),
        sa.Column("embedding_model", sa.Text, nullable=True),
        sa.Column("embedding_api_key", sa.Text, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("runtime_llm_config")
