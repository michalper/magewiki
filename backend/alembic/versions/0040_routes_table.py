"""routes.xml declared facts -- Phase 22, part 1. Feeds the
route_id_conflict/frontname_conflict cross-module checks (0041): Magento
merges every module's etc/frontend|adminhtml/routes.xml declarations by area,
so a duplicate route id (breaks reverse-URL generation) or a duplicate
frontName (breaks URL dispatch) within the same area is genuinely ambiguous,
same risk class as a duplicate acl.xml resource id or indexer.xml id.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-13

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_routes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("area", sa.Text, nullable=False),
        sa.Column("route_id", sa.Text, nullable=False),
        sa.Column("front_name", sa.Text, nullable=False),
    )
    op.create_index("ix_module_routes_route_id", "module_routes", ["route_id"])
    op.create_index("ix_module_routes_front_name", "module_routes", ["front_name"])


def downgrade() -> None:
    op.drop_table("module_routes")
