"""Phase 10: composer_package_requirements, packagist_cache, CVE/abandoned check_types

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "composer_package_requirements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_name", sa.Text, nullable=False),
        sa.Column("constraint", sa.Text, nullable=False),
        sa.Column("is_dev", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_composer_package_requirements_module_id", "composer_package_requirements", ["module_id"]
    )

    op.create_table(
        "packagist_cache",
        sa.Column("cache_key", sa.Text, primary_key=True),
        sa.Column("response_json", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret')",
    )
    op.drop_table("packagist_cache")
    op.drop_table("composer_package_requirements")
