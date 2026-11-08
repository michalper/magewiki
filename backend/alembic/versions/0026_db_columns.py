"""db_schema.xml declared columns — a column-level extension of db_tables
(0019), added so a cross-module conflict on the same table's same column
(different type or nullability) can be detected. Table-level facts already
existed; this adds one flat row per column (name/xsi:type/nullable), not a
full breakdown (length/identity/default aren't captured yet).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-08

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "db_columns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.Text, nullable=False),
        sa.Column("column_name", sa.Text, nullable=False),
        sa.Column("xsi_type", sa.Text, nullable=False),
        sa.Column("nullable", sa.Boolean, nullable=True),
    )
    op.create_index("ix_db_columns_table_name", "db_columns", ["table_name"])


def downgrade() -> None:
    op.drop_table("db_columns")
