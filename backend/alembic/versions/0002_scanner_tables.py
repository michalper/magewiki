"""scanner tables: modules, dependencies, php classes/methods, di/events

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repo_root", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("setup_version", sa.Text, nullable=True),
        sa.Column("composer_name", sa.Text, nullable=True),
        sa.Column("composer_type", sa.Text, nullable=True),
        sa.Column("license", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("scan_warnings", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.UniqueConstraint("repo_root", "name", name="uq_modules_repo_root_name"),
    )

    op.create_table(
        "module_dependencies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_name", sa.Text, nullable=False),
    )

    op.create_table(
        "php_classes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fqcn", sa.Text, nullable=False),
        sa.Column("namespace", sa.Text, nullable=True),
        sa.Column("class_name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("extends", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("implements", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=True),
        sa.Column("end_line", sa.Integer, nullable=True),
        sa.Column("is_plugin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_observer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role_signals", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.UniqueConstraint("module_id", "fqcn", name="uq_php_classes_module_fqcn"),
    )
    op.create_index("ix_php_classes_fqcn", "php_classes", ["fqcn"])

    op.create_table(
        "php_class_methods",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("php_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=True),
        sa.Column("end_line", sa.Integer, nullable=True),
    )

    op.create_table(
        "di_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("for_type", sa.Text, nullable=False),
        sa.Column("preference_type", sa.Text, nullable=False),
    )

    op.create_table(
        "di_plugins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intercepted_type", sa.Text, nullable=False),
        sa.Column("plugin_name", sa.Text, nullable=False),
        sa.Column("plugin_class", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=True),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_di_plugins_intercepted_type", "di_plugins", ["intercepted_type"])
    op.create_index("ix_di_plugins_plugin_class", "di_plugins", ["plugin_class"])

    op.create_table(
        "event_observers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_name", sa.Text, nullable=False),
        sa.Column("observer_name", sa.Text, nullable=False),
        sa.Column("observer_class", sa.Text, nullable=False),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_event_observers_event_name", "event_observers", ["event_name"])
    op.create_index("ix_event_observers_observer_class", "event_observers", ["observer_class"])


def downgrade() -> None:
    op.drop_table("event_observers")
    op.drop_table("di_plugins")
    op.drop_table("di_preferences")
    op.drop_table("php_class_methods")
    op.drop_table("php_classes")
    op.drop_table("module_dependencies")
    op.drop_table("modules")
