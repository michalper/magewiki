"""menu.xml/cache.xml declared facts -- Phase 25, part 1. Feeds the
menu_item_id_conflict/cache_type_conflict cross-module checks (0046):
Magento's admin menu builder throws a hard error on a duplicate menu.xml
id, while a duplicate cache.xml name with a different instance is the
same silent-merge-override risk as a di.xml preference.

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-13

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_menu_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
    )
    op.create_index("ix_module_menu_items_menu_item_id", "module_menu_items", ["menu_item_id"])

    op.create_table(
        "module_cache_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_type_id", sa.Text, nullable=False),
        sa.Column("instance", sa.Text, nullable=True),
    )
    op.create_index("ix_module_cache_types_cache_type_id", "module_cache_types", ["cache_type_id"])


def downgrade() -> None:
    op.drop_table("module_cache_types")
    op.drop_table("module_menu_items")
