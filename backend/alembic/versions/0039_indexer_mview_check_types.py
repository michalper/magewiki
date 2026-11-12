"""Add indexer_id_conflict, view_id_conflict check_types -- Phase 20, part 2.

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-12

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | None = "0038"
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
        "'composer_conflict','webapi_route_conflict','db_schema_conflict','circular_dependency',"
        "'license_risk','phpunit_failure','preference_conflict','cron_job_conflict',"
        "'graphql_field_conflict','acl_resource_conflict','missing_acl',"
        "'indexer_id_conflict','view_id_conflict')",
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
        "'license_risk','phpunit_failure','preference_conflict','cron_job_conflict',"
        "'graphql_field_conflict','acl_resource_conflict','missing_acl')",
    )
