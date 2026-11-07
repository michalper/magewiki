"""di.xml <virtualType> declarations — a module's own composed classes (common
pattern for UI Component data providers, collections with preset filters),
previously invisible since only <preference> and <plugin> were parsed from
this same file.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "di_virtual_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("virtual_type", sa.Text, nullable=False),
    )
    op.create_index("ix_di_virtual_types_name", "di_virtual_types", ["name"])


def downgrade() -> None:
    op.drop_table("di_virtual_types")
