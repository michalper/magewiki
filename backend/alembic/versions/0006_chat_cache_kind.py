"""extend analysis_cache.kind with 'chat' so chat costs share the monthly budget ledger

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind", "analysis_cache", "kind IN ('file_summary','module_synthesis','embedding','chat')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_analysis_cache_kind", "analysis_cache", type_="check")
    op.create_check_constraint(
        "ck_analysis_cache_kind", "analysis_cache", "kind IN ('file_summary','module_synthesis','embedding')"
    )
