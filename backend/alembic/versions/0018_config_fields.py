"""etc/adminhtml/system.xml admin config fields — part of Phase 14 (structural
facts from webapi/crontab/db_schema/system.xml instead of LLM-guessed). Closes
what the synthesis prompt previously asked the LLM to guess.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.Text, nullable=False),
        sa.Column("group_id", sa.Text, nullable=False),
        sa.Column("field_id", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("field_type", sa.Text, nullable=True),
    )
    op.create_index("ix_config_fields_section_id", "config_fields", ["section_id"])


def downgrade() -> None:
    op.drop_table("config_fields")
