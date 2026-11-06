"""AI analysis: analysis_cache, file_analyses, module_docs

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("response", postgresql.JSONB, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("content_hash", "model", "prompt_version", "kind", name="uq_analysis_cache_key"),
    )
    op.create_index("ix_analysis_cache_created_at", "analysis_cache", ["created_at"])
    op.create_check_constraint(
        "ck_analysis_cache_kind", "analysis_cache", "kind IN ('file_summary','module_synthesis')"
    )

    op.create_table(
        "file_analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relative_path", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("cache_id", sa.Integer, sa.ForeignKey("analysis_cache.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("module_id", "relative_path", name="uq_file_analyses_module_relpath"),
    )

    op.create_table(
        "module_docs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("cache_id", sa.Integer, sa.ForeignKey("analysis_cache.id"), nullable=False),
        sa.Column("doc", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("module_id", name="uq_module_docs_module_id"),
    )


def downgrade() -> None:
    op.drop_table("module_docs")
    op.drop_table("file_analyses")
    op.drop_table("analysis_cache")
