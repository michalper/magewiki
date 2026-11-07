"""GraphQL schema facts (etc/schema.graphqls) — Query/Mutation/type fields a module
adds, with the backing PHP resolver class when declared via @resolver(class: "...").

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graphql_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_type", sa.Text, nullable=False),
        sa.Column("type_name", sa.Text, nullable=False),
        sa.Column("field_name", sa.Text, nullable=False),
        sa.Column("resolver_class", sa.Text, nullable=True),
    )
    op.create_index("ix_graphql_fields_type_name", "graphql_fields", ["type_name"])
    op.create_index("ix_graphql_fields_resolver_class", "graphql_fields", ["resolver_class"])


def downgrade() -> None:
    op.drop_table("graphql_fields")
