"""Real PHPUnit execution: phpunit_tests_run/phpunit_tests_failed/
phpunit_coverage_percent columns on modules, plus a new phpunit_failure
check_type for individual test failures. See check_php_unit_tests
(app/scanner/php_analyzer_client.py) and run_phpunit (php-analyzer/public/
index.php) -- the first check in this project that actually executes a
scanned module's own code rather than only parsing/analysing it.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-08

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("phpunit_tests_run", sa.Integer, nullable=True))
    op.add_column("modules", sa.Column("phpunit_tests_failed", sa.Integer, nullable=True))
    op.add_column("modules", sa.Column("phpunit_coverage_percent", sa.Float, nullable=True))

    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency',"
        "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
        "'magento_php_incompatible','magento_version_blocker','plugin_conflict','phpmetrics_issue',"
        "'composer_conflict','webapi_route_conflict','db_schema_conflict','circular_dependency',"
        "'license_risk','phpunit_failure')",
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
        "'composer_conflict','webapi_route_conflict','db_schema_conflict','circular_dependency',"
        "'license_risk')",
    )

    op.drop_column("modules", "phpunit_coverage_percent")
    op.drop_column("modules", "phpunit_tests_failed")
    op.drop_column("modules", "phpunit_tests_run")
