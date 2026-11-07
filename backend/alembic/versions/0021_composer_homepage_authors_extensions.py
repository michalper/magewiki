"""composer.json homepage/authors/required PHP extensions — already-parsed
facts that were never actually surfaced anywhere (license had the exact
same problem, fixed here too by finally exposing it via the API).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("homepage", sa.Text, nullable=True))
    op.add_column("modules", sa.Column("authors", sa.ARRAY(sa.Text), nullable=True))
    op.add_column("modules", sa.Column("php_extensions", sa.ARRAY(sa.Text), nullable=True))


def downgrade() -> None:
    op.drop_column("modules", "php_extensions")
    op.drop_column("modules", "authors")
    op.drop_column("modules", "homepage")
