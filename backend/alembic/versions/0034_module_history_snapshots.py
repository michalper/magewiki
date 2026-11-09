"""Phase 16: module_history_snapshots -- one row per module per real change
(hash/state/enabled/finding_counts), written after Phase C's cross-module
conflict detection so finding_counts are complete for the scan. Dedup at
write time (see app/scanner/history.py) keeps this from growing on every
routine no-op rescan, the exact unbounded-growth failure CLAUDE.md's
"Operational lessons" section already names from v1's own production
history.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_history_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("current_hash", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=True),
        sa.Column("finding_counts", JSONB, nullable=False),
    )
    op.create_index(
        "ix_module_history_snapshots_module_id", "module_history_snapshots", ["module_id", "scanned_at"]
    )


def downgrade() -> None:
    op.drop_table("module_history_snapshots")
