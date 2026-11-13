"""acl.xml declared ACL resources -- Phase 19, part 1. Feeds the
acl_resource_conflict cross-module check (0037): Magento merges every
module's ACL resource tree by id, so a duplicate id across modules is
genuinely ambiguous, same risk class as a duplicate webapi.xml route.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "acl_resources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("parent_id", sa.Text, nullable=True),
    )
    op.create_index("ix_acl_resources_resource_id", "acl_resources", ["resource_id"])


def downgrade() -> None:
    op.drop_table("acl_resources")
