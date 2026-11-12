from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, controller_body: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    controller_dir = module_dir / "Controller" / "Adminhtml" / "Index"
    controller_dir.mkdir(parents=True)
    (controller_dir / "Index.php").write_text(controller_body, encoding="utf-8")


@pytest.mark.asyncio
async def test_scan_flags_an_admin_controller_with_no_admin_resource(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(
        repo_root / "app" / "code" / "Vendor" / "A",
        "Vendor_A",
        "<?php\nnamespace Vendor\\A\\Controller\\Adminhtml\\Index;\nclass Index {\n    public function execute() {}\n}\n",
    )

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    module = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "missing_acl"
            )
        )
    ).all()

    assert len(findings) == 1
    assert "Vendor\\A\\Controller\\Adminhtml\\Index\\Index" in findings[0].message
    assert findings[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_does_not_flag_an_admin_controller_with_an_admin_resource(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(
        repo_root / "app" / "code" / "Vendor" / "A",
        "Vendor_A",
        "<?php\nnamespace Vendor\\A\\Controller\\Adminhtml\\Index;\n"
        "class Index {\n    const ADMIN_RESOURCE = 'Vendor_A::index';\n    public function execute() {}\n}\n",
    )

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    module = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "missing_acl"
            )
        )
    ).all()
    assert findings == []
