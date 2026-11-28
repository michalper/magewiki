"""etc/email_templates.xml declared facts. Feeds the email_template_id_conflict
cross-module check (0051): Magento merges every module's email templates into
one global id namespace, so a duplicate id across modules is the same
silent-merge-override risk as a duplicate widget.xml/menu.xml id.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-28

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_email_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("file", sa.Text, nullable=True),
        sa.Column("type", sa.Text, nullable=True),
        sa.Column("area", sa.Text, nullable=True),
    )
    op.create_index("ix_module_email_templates_template_id", "module_email_templates", ["template_id"])


def downgrade() -> None:
    op.drop_table("module_email_templates")
