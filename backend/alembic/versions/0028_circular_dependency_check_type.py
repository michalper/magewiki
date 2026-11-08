"""Add circular_dependency check_type

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-08

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency',"
        "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
        "'magento_php_incompatible','magento_version_blocker','plugin_conflict','phpmetrics_issue',"
        "'composer_conflict','webapi_route_conflict','db_schema_conflict','circular_dependency')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency',"
        "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
        "'magento_php_incompatible','magento_version_blocker','plugin_conflict','phpmetrics_issue',"
        "'composer_conflict','webapi_route_conflict','db_schema_conflict')",
    )
