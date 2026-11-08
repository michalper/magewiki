from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, depends_on: str | None) -> None:
    (module_dir / "etc").mkdir(parents=True)
    sequence = f'<sequence><module name="{depends_on}"/></sequence>' if depends_on else ""
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}">{sequence}</module></config>', encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_scan_flags_a_real_three_module_circular_dependency(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor_B")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor_C")
    _write_module(repo_root / "app" / "code" / "Vendor" / "C", "Vendor_C", "Vendor_A")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 3

    module_a = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "circular_dependency", Module.repo_root == str(repo_root))
        )
    ).all()

    assert len(findings) == 3
    assert {f.module_id for f in findings} == {
        module_a.id,
        (await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B"))).id,
        (await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_C"))).id,
    }
    assert findings[0].severity == "warning"
    assert "setup:upgrade fails outright" in findings[0].message


@pytest.mark.asyncio
async def test_scan_does_not_flag_a_simple_dependency_chain(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor_B")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", None)

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "circular_dependency", Module.repo_root == str(repo_root))
        )
    ).all()
    assert findings == []
