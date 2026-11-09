"""extend analysis_cache.kind with 'query_rewrite' so query-rewrite costs share the monthly budget ledger

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-09

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind",
        "analysis_cache",
        "kind IN ('file_summary','module_synthesis','embedding','chat','rerank','query_rewrite')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind",
        "analysis_cache",
        "kind IN ('file_summary','module_synthesis','embedding','chat','rerank')",
    )
