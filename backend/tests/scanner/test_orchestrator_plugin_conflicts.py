from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, di_xml: str, plugin_php: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "etc" / "di.xml").write_text(di_xml, encoding="utf-8")
    (module_dir / "composer.json").write_text("{}", encoding="utf-8")
    plugin_dir = module_dir / "Plugin"
    plugin_dir.mkdir()
    (plugin_dir / "SavePlugin.php").write_text(plugin_php, encoding="utf-8")


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_around_plugin_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    di_xml = """<?xml version="1.0"?>
<config>
  <type name="Vendor\\Shared\\Model\\Order">
    <plugin name="save_plugin" type="{plugin_class}" sortOrder="10" />
  </type>
</config>
"""
    plugin_php_tpl = """<?php
namespace {namespace};

class SavePlugin
{{
    public function aroundSave($subject, callable $proceed)
    {{
        return $proceed();
    }}
}}
"""

    _write_module(
        repo_root / "app" / "code" / "Vendor" / "A",
        "Vendor_A",
        di_xml.format(plugin_class="Vendor\\A\\Plugin\\SavePlugin"),
        plugin_php_tpl.format(namespace="Vendor\\A\\Plugin"),
    )
    _write_module(
        repo_root / "app" / "code" / "Vendor" / "B",
        "Vendor_B",
        di_xml.format(plugin_class="Vendor\\B\\Plugin\\SavePlugin"),
        plugin_php_tpl.format(namespace="Vendor\\B\\Plugin"),
    )

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 2

    module_a = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )
    module_b = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B")
    )

    findings_a = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_a.id,
                ModuleQualityFinding.check_type == "plugin_conflict",
            )
        )
    ).all()
    findings_b = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_b.id,
                ModuleQualityFinding.check_type == "plugin_conflict",
            )
        )
    ).all()

    assert len(findings_a) == 1
    assert len(findings_b) == 1
    assert "around" in findings_a[0].message
    assert "Vendor\\A\\Plugin\\SavePlugin" in findings_a[0].message
    assert "Vendor\\B\\Plugin\\SavePlugin" in findings_a[0].message
    assert findings_a[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_does_not_flag_plugins_on_different_methods(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    di_xml_a = """<?xml version="1.0"?>
<config>
  <type name="Vendor\\Shared\\Model\\Order">
    <plugin name="save_plugin" type="Vendor\\A\\Plugin\\SavePlugin" />
  </type>
</config>
"""
    di_xml_b = """<?xml version="1.0"?>
<config>
  <type name="Vendor\\Shared\\Model\\Order">
    <plugin name="delete_plugin" type="Vendor\\B\\Plugin\\SavePlugin" />
  </type>
</config>
"""
    plugin_php_tpl = """<?php
namespace {namespace};

class SavePlugin
{{
    public function {method}($subject, callable $proceed)
    {{
        return $proceed();
    }}
}}
"""

    _write_module(
        repo_root / "app" / "code" / "Vendor" / "A",
        "Vendor_A",
        di_xml_a,
        plugin_php_tpl.format(namespace="Vendor\\A\\Plugin", method="beforeSave"),
    )
    _write_module(
        repo_root / "app" / "code" / "Vendor" / "B",
        "Vendor_B",
        di_xml_b,
        plugin_php_tpl.format(namespace="Vendor\\B\\Plugin", method="beforeDelete"),
    )

    await anext_drain(scan_repository_events(str(repo_root), db_session))

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "plugin_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert findings == []


async def anext_drain(gen):
    async for _ in gen:
        pass
