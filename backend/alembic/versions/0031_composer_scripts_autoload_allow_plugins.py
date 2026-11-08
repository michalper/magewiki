"""Surface composer.json's scripts/autoload.psr-4/config.allow-plugins on
Module -- parsed facts that were deliberately deferred alongside homepage/
authors/php_extensions (see that decision's own "lower-value, more niche
fields... worth adding individually if ever asked for" note), added once
actually asked for. See app/scanner/composer_json.py.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("composer_scripts", sa.ARRAY(sa.Text), nullable=True))
    op.add_column("modules", sa.Column("composer_autoload_psr4", JSONB, nullable=True))
    op.add_column("modules", sa.Column("composer_allow_plugins", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("modules", "composer_allow_plugins")
    op.drop_column("modules", "composer_autoload_psr4")
    op.drop_column("modules", "composer_scripts")
