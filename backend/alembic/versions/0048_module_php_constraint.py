"""module_php_constraint -- persists each module's own require.php constraint
(parsed at scan time from composer.json, previously used only transiently
inside check_magento_upgrade_readiness and then discarded). Needed so the
Phase 27 upgrade-impact "what if I upgrade to Magento X" query can compare
every already-scanned module against an arbitrary chosen release without
re-reading composer.json from disk.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("php_constraint", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("modules", "php_constraint")
