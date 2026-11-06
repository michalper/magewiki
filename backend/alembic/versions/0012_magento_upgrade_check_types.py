"""Phase 13: magento upgrade-readiness check_types

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency',"
        "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
        "'magento_php_incompatible','magento_version_blocker')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_module_quality_findings_check_type", "module_quality_findings", type_="check")
    op.create_check_constraint(
        "ck_module_quality_findings_check_type",
        "module_quality_findings",
        "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
        "'security_advisory','abandoned_dependency','outdated_dependency',"
        "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue')",
    )
