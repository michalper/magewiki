"""webapi.xml REST endpoints — part of Phase 14 (structural facts from
webapi/crontab/db_schema/system.xml instead of LLM-guessed).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webapi_routes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("http_method", sa.Text, nullable=False),
        sa.Column("service_class", sa.Text, nullable=False),
        sa.Column("service_method", sa.Text, nullable=False),
        sa.Column("acl_resource", sa.Text, nullable=True),
    )
    op.create_index("ix_webapi_routes_url", "webapi_routes", ["url"])


def downgrade() -> None:
    op.drop_table("webapi_routes")
