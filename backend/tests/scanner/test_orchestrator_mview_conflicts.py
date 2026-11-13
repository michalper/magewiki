from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, mview_class: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "etc" / "mview.xml").write_text(
        '<?xml version="1.0"?><config>'
        f'<view id="shared_view" class="{mview_class}" group="indexer"/>'
        "</config>",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_mview_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\A\\Mview\\Sample")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor\\B\\Mview\\Sample")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 2

    module_a = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )
    module_b = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B")
    )

    for module in (module_a, module_b):
        findings = (
            await db_session.scalars(
                select(ModuleQualityFinding).where(
                    ModuleQualityFinding.module_id == module.id,
                    ModuleQualityFinding.check_type == "view_id_conflict",
                )
            )
        ).all()
        assert len(findings) == 1
        assert "shared_view" in findings[0].message
        assert findings[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_does_not_flag_distinct_view_ids(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\A\\Mview\\Sample")
    (repo_root / "app" / "code" / "Vendor" / "B" / "etc").mkdir(parents=True)
    (repo_root / "app" / "code" / "Vendor" / "B" / "etc" / "module.xml").write_text(
        '<?xml version="1.0"?><config><module name="Vendor_B" /></config>', encoding="utf-8"
    )
    (repo_root / "app" / "code" / "Vendor" / "B" / "etc" / "mview.xml").write_text(
        '<?xml version="1.0"?><config><view id="distinct_view" class="Vendor\\B\\Mview\\Sample" group="indexer"/></config>',
        encoding="utf-8",
    )

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "view_id_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert findings == []
