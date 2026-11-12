"""indexer.xml/mview.xml declared facts -- Phase 20, part 1. Feeds the
indexer_id_conflict/view_id_conflict cross-module checks (0039): Magento
merges every module's indexer/mview declarations by id, so a duplicate id
across modules is genuinely ambiguous, same risk class as a duplicate
acl.xml resource id or webapi.xml route.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_indexers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("indexer_id", sa.Text, nullable=False),
        sa.Column("view_id", sa.Text, nullable=True),
        sa.Column("class_name", sa.Text, nullable=True),
    )
    op.create_index("ix_module_indexers_indexer_id", "module_indexers", ["indexer_id"])

    op.create_table(
        "module_mviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("view_id", sa.Text, nullable=False),
        sa.Column("class_name", sa.Text, nullable=True),
        sa.Column("group_name", sa.Text, nullable=True),
    )
    op.create_index("ix_module_mviews_view_id", "module_mviews", ["view_id"])


def downgrade() -> None:
    op.drop_table("module_mviews")
    op.drop_table("module_indexers")
