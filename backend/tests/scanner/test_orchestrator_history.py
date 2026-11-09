from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleHistorySnapshot
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, setup_version: str = "1.0.0") -> None:
    (module_dir / "etc").mkdir(parents=True, exist_ok=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" setup_version="{setup_version}" /></config>',
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_first_scan_writes_one_baseline_snapshot(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    module = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    snapshots = (
        await db_session.scalars(
            select(ModuleHistorySnapshot).where(ModuleHistorySnapshot.module_id == module.id)
        )
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].current_hash == module.current_hash
    assert snapshots[0].state == module.state


@pytest.mark.asyncio
async def test_no_op_rescan_writes_no_new_snapshot(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass
    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    module = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    snapshots = (
        await db_session.scalars(
            select(ModuleHistorySnapshot).where(ModuleHistorySnapshot.module_id == module.id)
        )
    ).all()
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_a_code_change_writes_a_second_snapshot(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "app" / "code" / "Vendor" / "A"
    _write_module(module_dir, "Vendor_A")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    _write_module(module_dir, "Vendor_A", setup_version="1.0.1")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    module = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    snapshots = (
        await db_session.scalars(
            select(ModuleHistorySnapshot)
            .where(ModuleHistorySnapshot.module_id == module.id)
            .order_by(ModuleHistorySnapshot.scanned_at)
        )
    ).all()
    assert len(snapshots) == 2
    assert snapshots[0].current_hash != snapshots[1].current_hash
    assert snapshots[1].current_hash == module.current_hash
