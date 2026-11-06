import shutil
from pathlib import Path

import pytest

from app.db import async_session_factory
from app.scanner.orchestrator import scan_paths_events


def _make_module(repo_root: Path, demo_module_path: Path, name: str) -> None:
    module_dir = repo_root / "app" / "code" / "Vendor" / name
    shutil.copytree(demo_module_path, module_dir)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="Vendor_{name}"/></config>'
    )


@pytest.mark.asyncio
async def test_a_single_store_path_behaves_identically_to_scan_repository_events(
    tmp_path: Path, demo_module_path: Path, db_session
):
    """Regression guard for the delegation branch: scan_paths_events() must
    be a drop-in replacement for scan_repository_events() whenever `path`
    resolves to zero or one roots — it's what POST /scan[/stream] call
    exclusively now, so every existing single-store scan must keep behaving
    exactly as before.
    """
    repo_root = tmp_path / "repo"
    _make_module(repo_root, demo_module_path, "One")

    events = [event async for event in scan_paths_events(str(repo_root), db_session)]

    assert events[0] == {"event": "discovered", "total": 1}
    assert events[-1]["event"] == "done"
    assert events[-1]["result"].modules_created == 1
    assert events[-1]["result"].stores_scanned == 1
    assert not any(e["event"] == "store" for e in events)


@pytest.mark.asyncio
async def test_a_container_directory_scans_every_store_and_combines_the_result(
    tmp_path: Path, demo_module_path: Path, db_session
):
    sites = tmp_path / "sites"
    store_a = sites / "store-a"
    store_b = sites / "store-b"
    _make_module(store_a, demo_module_path, "FromA")
    _make_module(store_b, demo_module_path, "FromB")

    events = [event async for event in scan_paths_events(str(sites), db_session)]

    store_events = [e for e in events if e["event"] == "store"]
    assert [(e["name"], e["index"], e["total"]) for e in store_events] == [
        ("store-a", 1, 2),
        ("store-b", 2, 2),
    ]

    module_events = [e for e in events if e["event"] == "module"]
    assert {e["name"] for e in module_events} == {"Vendor_FromA", "Vendor_FromB"}

    result = events[-1]["result"]
    assert events[-1]["event"] == "done"
    assert result.stores_scanned == 2
    assert result.modules_found == 2
    assert result.modules_created == 2
    assert {m.name for m in result.modules} == {"Vendor_FromA", "Vendor_FromB"}


@pytest.mark.asyncio
async def test_each_store_is_persisted_under_its_own_distinct_repo_root(
    tmp_path: Path, demo_module_path: Path, db_session
):
    from sqlalchemy import select

    from app.models import Module

    sites = tmp_path / "sites"
    store_a = sites / "store-a"
    store_b = sites / "store-b"
    _make_module(store_a, demo_module_path, "Shared")
    _make_module(store_b, demo_module_path, "Shared")

    async for _ in scan_paths_events(str(sites), db_session):
        pass

    async with async_session_factory() as session:
        modules = (await session.scalars(select(Module).where(Module.name == "Vendor_Shared"))).all()

    assert {m.repo_root for m in modules} == {str(store_a.resolve()), str(store_b.resolve())}
