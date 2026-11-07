"""Message queue topology (communication.xml + queue_topology.xml +
queue_consumer.xml), merged by topic/queue name into one fact per binding.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_bindings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("destination", sa.Text, nullable=True),
        sa.Column("consumer_name", sa.Text, nullable=True),
        sa.Column("handler_class", sa.Text, nullable=True),
        sa.Column("handler_method", sa.Text, nullable=True),
    )
    op.create_index("ix_queue_bindings_topic", "queue_bindings", ["topic"])


def downgrade() -> None:
    op.drop_table("queue_bindings")
