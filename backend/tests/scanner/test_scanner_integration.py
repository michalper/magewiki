from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.models import DiPlugin, DiPreference, EventObserver, Module, ModuleDependency, PhpClass
from app.scanner.orchestrator import scan_repository


async def _delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


@pytest.mark.asyncio
async def test_scan_repository_is_idempotent(demo_store_path: Path, db_session):
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    first = await scan_repository(repo_root, db_session)
    assert first.modules_found == 1
    assert first.modules_created == 1
    assert first.modules_updated == 0

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    assert module is not None
    assert module.enabled is True
    assert module.composer_name == "vendor/module-sample"

    dep_count_1 = len((await db_session.scalars(
        select(ModuleDependency).where(ModuleDependency.module_id == module.id)
    )).all())
    class_count_1 = len((await db_session.scalars(
        select(PhpClass).where(PhpClass.module_id == module.id)
    )).all())
    pref_count_1 = len((await db_session.scalars(
        select(DiPreference).where(DiPreference.module_id == module.id)
    )).all())
    plugin_count_1 = len((await db_session.scalars(
        select(DiPlugin).where(DiPlugin.module_id == module.id)
    )).all())
    observer_count_1 = len((await db_session.scalars(
        select(EventObserver).where(EventObserver.module_id == module.id)
    )).all())

    assert dep_count_1 == 1
    assert class_count_1 == 2
    assert pref_count_1 == 1
    assert plugin_count_1 == 1
    assert observer_count_1 == 1

    # Re-scan the same repo: row counts must stay the same, not double.
    second = await scan_repository(repo_root, db_session)
    assert second.modules_found == 1
    assert second.modules_created == 0
    assert second.modules_updated == 1

    module_id = module.id  # same id across re-scan (UPDATE in place)
    assert (await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )).id == module_id

    dep_count_2 = len((await db_session.scalars(
        select(ModuleDependency).where(ModuleDependency.module_id == module_id)
    )).all())
    class_count_2 = len((await db_session.scalars(
        select(PhpClass).where(PhpClass.module_id == module_id)
    )).all())

    assert dep_count_2 == dep_count_1
    assert class_count_2 == class_count_1


@pytest.mark.asyncio
async def test_scan_repository_flags_plugin_and_observer_classes(demo_store_path: Path, db_session):
    repo_root = str(demo_store_path.resolve())
    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    classes = (await db_session.scalars(select(PhpClass).where(PhpClass.module_id == module.id))).all()
    by_name = {c.class_name: c for c in classes}

    plugin = by_name["SampleCheckoutPlugin"]
    assert plugin.is_plugin is True
    assert "directory_convention" in plugin.role_signals
    assert "di_xml_plugin" in plugin.role_signals

    observer = by_name["SampleOrderObserver"]
    assert observer.is_observer is True
    assert "directory_convention" in observer.role_signals
    assert "events_xml_observer" in observer.role_signals
