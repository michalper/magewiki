"""crontab.xml scheduled jobs — part of Phase 14 (structural facts from
webapi/crontab/db_schema/system.xml instead of LLM-guessed).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_name", sa.Text, nullable=False),
        sa.Column("instance_class", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("schedule", sa.Text, nullable=True),
    )
    op.create_index("ix_cron_jobs_job_name", "cron_jobs", ["job_name"])


def downgrade() -> None:
    op.drop_table("cron_jobs")
