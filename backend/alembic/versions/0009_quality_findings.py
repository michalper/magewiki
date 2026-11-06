"""Phase 9: module_quality_findings table, Module.has_readme/has_tests

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-06

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("has_readme", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("modules", sa.Column("has_tests", sa.Boolean, nullable=False, server_default="false"))

    op.create_table(
        "module_quality_findings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=True),
        sa.Column("line", sa.Integer, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
    )
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret')",
    )
    op.create_check_constraint(
        "ck_module_quality_findings_severity",
        "module_quality_findings",
        "severity IN ('blocking','warning','info')",
    )
    op.create_index("ix_module_quality_findings_module_id", "module_quality_findings", ["module_id"])


def downgrade() -> None:
    op.drop_table("module_quality_findings")
    op.drop_column("modules", "has_tests")
    op.drop_column("modules", "has_readme")
