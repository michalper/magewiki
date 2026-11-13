from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, virtual_type: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "etc" / "di.xml").write_text(
        f'<?xml version="1.0"?><config><virtualType name="Vendor\\Shared\\VirtualFoo" '
        f'type="{virtual_type}" /></config>',
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_virtual_type_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\A\\Model\\Foo")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor\\B\\Model\\Foo")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 2

    module_a = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    module_b = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B"))

    findings_a = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_a.id,
                ModuleQualityFinding.check_type == "virtual_type_conflict",
            )
        )
    ).all()
    findings_b = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_b.id,
                ModuleQualityFinding.check_type == "virtual_type_conflict",
            )
        )
    ).all()

    assert len(findings_a) == 1
    assert len(findings_b) == 1
    assert "Vendor\\Shared\\VirtualFoo" in findings_a[0].message
    assert findings_a[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_does_not_flag_agreeing_virtual_types(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\Shared\\Model\\Foo")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor\\Shared\\Model\\Foo")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "virtual_type_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert findings == []
