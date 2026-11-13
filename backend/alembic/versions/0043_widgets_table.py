"""widget.xml declared facts -- feature-search round 4, part 3. Feeds the
widget_id_conflict cross-module check (0044): Magento merges every module's
view/{base,frontend,adminhtml}/widget.xml declarations into one global id
namespace, so a duplicate widget id is genuinely ambiguous, same risk class
as a duplicate indexer.xml id.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-13

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_widgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("widget_id", sa.Text, nullable=False),
        sa.Column("class_name", sa.Text, nullable=False),
    )
    op.create_index("ix_module_widgets_widget_id", "module_widgets", ["widget_id"])


def downgrade() -> None:
    op.drop_table("module_widgets")
