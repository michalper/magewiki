import shutil
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

from app.models import (
    DiPlugin,
    DiPreference,
    EventObserver,
    FileHash,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
)
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
    # composer.json, etc/module.xml, etc/di.xml, etc/events.xml, registration.php,
    # Plugin/SampleCheckoutPlugin.php, Observer/SampleOrderObserver.php
    assert first.tasks_enqueued == 7

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    assert module is not None
    assert module.enabled is True
    assert module.composer_name == "vendor/module-sample"
    assert module.state == "pending"
    assert module.pending_file_count == 7
    assert module.analyzed_hash is None
    assert module.current_hash != ""

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

    # Re-scan the same repo: row counts must stay the same, not double, and —
    # the actual Phase 2 done-criterion — an unchanged re-scan creates 0 tasks.
    second = await scan_repository(repo_root, db_session)
    assert second.modules_found == 1
    assert second.modules_created == 0
    assert second.modules_updated == 1
    assert second.tasks_enqueued == 0

    # Nothing changed, so state/pending_file_count must be left untouched by the
    # no-op re-scan — a module must not bounce through pending on an empty diff.
    await db_session.refresh(module)
    assert module.state == "pending"
    assert module.pending_file_count == 7

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
async def test_scan_repository_detects_a_single_changed_file(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    first = await scan_repository(repo_root, db_session)
    assert first.tasks_enqueued == 7

    observer_file = repo_copy / "app/code/Vendor/Module/Observer/SampleOrderObserver.php"
    observer_file.write_text(observer_file.read_text() + "\n// changed\n")

    second = await scan_repository(repo_root, db_session)
    assert second.tasks_enqueued == 1
    assert second.modules[0].files_added == 0
    assert second.modules[0].files_changed == 1
    assert second.modules[0].files_removed == 0


@pytest.mark.asyncio
async def test_scan_repository_preserves_unanalyzed_status_on_a_no_op_rescan(
    demo_store_path: Path, db_session, tmp_path: Path
):
    """A FileHash left analyzed=False by a budget-paused analyze_file job must
    stay analyzed=False across a later rescan where that file's content is
    unchanged — the rescan must not assume "unchanged" means "was analyzed",
    or the file silently drops out of cli.py's budget-resume requeue
    (which only selects FileHash.analyzed.is_(False)) forever.
    """
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    await scan_repository(repo_root, db_session)
    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )

    # Simulate a budget pause: one file's analyze_file job never completed.
    await db_session.execute(
        update(FileHash)
        .where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
        .values(analyzed=False)
    )
    await db_session.commit()

    # Change an unrelated file so the scan has *some* diff to process, while
    # etc/module.xml's content stays byte-for-byte the same.
    observer_file = repo_copy / "app/code/Vendor/Module/Observer/SampleOrderObserver.php"
    observer_file.write_text(observer_file.read_text() + "\n// unrelated change\n")

    await scan_repository(repo_root, db_session)

    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    assert file_hash.analyzed is False


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


@pytest.mark.asyncio
async def test_scan_repository_records_quality_findings_and_replaces_them_on_rescan(
    demo_store_path: Path, db_session
):
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    # The demo-store fixture has no README and no tests dir, but its
    # composer.json is otherwise complete except for require-dev phpunit.
    assert module.has_readme is False
    assert module.has_tests is False

    findings = (
        await db_session.scalars(select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module.id))
    ).all()
    # Exact count isn't the point (Phase 12's PHP toolchain adds its own
    # findings to this same module on top of the composer-completeness one) —
    # just confirm the specific finding this test is actually about exists.
    composer_findings = [f for f in findings if f.check_type == "composer_completeness"]
    assert len(composer_findings) == 1
    assert "require-dev phpunit/phpunit" in composer_findings[0].message

    # Re-scan with no changes: the full-replace delete-then-reinsert must not
    # duplicate rows.
    await scan_repository(repo_root, db_session)
    findings_after_rescan = (
        await db_session.scalars(select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module.id))
    ).all()
    assert len(findings_after_rescan) == len(findings)
