"""db_schema.xml declared tables — part of Phase 14 (structural facts from
webapi/crontab/db_schema/system.xml instead of LLM-guessed). Table-level facts
(name/comment/column count), not a full column breakdown.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "db_tables",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.Text, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("column_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_db_tables_table_name", "db_tables", ["table_name"])


def downgrade() -> None:
    op.drop_table("db_tables")
