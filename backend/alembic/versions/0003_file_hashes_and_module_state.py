"""file hashes and module state machine

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_hashes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relative_path", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("analyzed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("module_id", "relative_path", name="uq_file_hashes_module_relpath"),
    )

    op.add_column("modules", sa.Column("state", sa.Text, nullable=False, server_default="pending"))
    op.add_column("modules", sa.Column("analyzed_hash", sa.Text, nullable=True))
    op.add_column("modules", sa.Column("current_hash", sa.Text, nullable=False, server_default=""))
    op.add_column("modules", sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"))
    op.add_column("modules", sa.Column("last_error", sa.Text, nullable=True))
    op.add_column("modules", sa.Column("pending_file_count", sa.Integer, nullable=False, server_default="0"))

    op.create_check_constraint(
        "ck_modules_state",
        "modules",
        "state IN ('pending','scanning','analyzing','embedding','up_to_date','failed','paused_budget')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_modules_state", "modules", type_="check")
    op.drop_column("modules", "pending_file_count")
    op.drop_column("modules", "last_error")
    op.drop_column("modules", "retry_count")
    op.drop_column("modules", "current_hash")
    op.drop_column("modules", "analyzed_hash")
    op.drop_column("modules", "state")
    op.drop_table("file_hashes")
