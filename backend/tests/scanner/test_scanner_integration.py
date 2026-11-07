import shutil
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models import (
    DiPlugin,
    DiPreference,
    EventObserver,
    FileHash,
    GraphQlField,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
)
from app.scanner.orchestrator import scan_repository
from tests.conftest import delete_module_if_present


@pytest.mark.asyncio
async def test_scan_repository_is_idempotent(demo_store_path: Path, db_session):
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

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
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

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
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

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
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

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


@pytest.mark.asyncio
async def test_scan_repository_persists_graphql_fields(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    schema_path = repo_copy / "app/code/Vendor/Module/etc/schema.graphqls"
    schema_path.write_text(
        'extend type Query {\n'
        '    vendorModuleWidget: String @resolver(class: "Vendor\\\\Module\\\\Model\\\\Resolver\\\\Widget")\n'
        '}\n',
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    fields = (await db_session.scalars(select(GraphQlField).where(GraphQlField.module_id == module.id))).all()

    assert len(fields) == 1
    assert fields[0].operation_type == "Query"
    assert fields[0].type_name == "Query"
    assert fields[0].field_name == "vendorModuleWidget"
    assert fields[0].resolver_class == "Vendor\\Module\\Model\\Resolver\\Widget"

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    fields_after_rescan = (
        await db_session.scalars(select(GraphQlField).where(GraphQlField.module_id == module.id))
    ).all()
    assert len(fields_after_rescan) == 1


@pytest.mark.asyncio
async def test_scan_repository_isolates_an_oserror_in_one_module(
    demo_store_path: Path, db_session, tmp_path: Path, monkeypatch
):
    # A permission error or TOCTOU race reading composer.json/di.xml/events.xml/
    # schema.graphqls for one module must not abort scanning every other module
    # in the store — only module_xml's own parse errors were isolated this way
    # before; this closes the same gap for the other Phase A parsers.
    repo_root_path = tmp_path / "store"
    shutil.copytree(demo_store_path, repo_root_path)

    broken_module = repo_root_path / "app/code/Vendor/ModuleTwo"
    shutil.copytree(repo_root_path / "app/code/Vendor/Module", broken_module)
    (broken_module / "etc/module.xml").write_text(
        (broken_module / "etc/module.xml").read_text().replace("Vendor_Module", "Vendor_ModuleTwo"),
        encoding="utf-8",
    )

    repo_root = str(repo_root_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await delete_module_if_present(db_session, repo_root, "Vendor_ModuleTwo")

    import app.scanner.orchestrator as orchestrator_module

    real_parse_composer_json = orchestrator_module.parse_composer_json

    def _raise_for_broken_module(path: Path):
        if "ModuleTwo" in str(path):
            raise OSError("simulated permission error")
        return real_parse_composer_json(path)

    monkeypatch.setattr(orchestrator_module, "parse_composer_json", _raise_for_broken_module)

    result = await scan_repository(repo_root, db_session)

    # The broken module's Phase A parse error is recorded as a warning (never
    # reaches Phase B, so it's not in result.modules) — the healthy module must
    # still complete normally despite it, proving the error didn't abort the scan.
    assert any("ModuleTwo" in w for w in result.warnings)
    statuses = {m.name: m.status for m in result.modules}
    assert statuses.get("Vendor_Module") == "created"

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    assert module is not None


@pytest.mark.asyncio
async def test_scan_repository_falls_back_to_composer_installed_version(
    demo_store_path: Path, db_session, tmp_path: Path
):
    # Real-world gap, flagged by a user looking at a real module's page: module.xml's
    # setup_version is optional since Magento 2.3's declarative schema and often
    # absent entirely on modern modules (confirmed against a real store: Amasty_Base
    # has no setup_version attribute at all) — Composer's own resolved version for
    # the package must still surface as this module's "version".
    repo_root_path = tmp_path / "store"
    shutil.copytree(demo_store_path, repo_root_path)

    module_xml_path = repo_root_path / "app/code/Vendor/Module/etc/module.xml"
    module_xml_path.write_text(
        module_xml_path.read_text().replace(' setup_version="1.0.0"', ""), encoding="utf-8"
    )

    composer_dir = repo_root_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text(
        '{"packages": [{"name": "vendor/module-sample", "version": "2.4.7"}]}', encoding="utf-8"
    )

    repo_root = str(repo_root_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    assert module.setup_version == "2.4.7"


@pytest.mark.asyncio
async def test_scan_repository_prefers_composer_version_over_a_stale_setup_version(
    demo_store_path: Path, db_session, tmp_path: Path
):
    # Real-world gap, flagged by a user looking at his own real module (Ordo_
    # Automation): module.xml's setup_version is an internal Magento upgrade-
    # script trigger, commonly left stale at its initial value for a module's
    # whole lifetime — Ordo_Automation's says "0.1.0" even though its real
    # composer.json version is well past that. Composer's version must win even
    # when setup_version IS present (not just as a fallback for when it's absent
    # — that's the separate Amasty_Base-shaped case covered above).
    repo_root_path = tmp_path / "store"
    shutil.copytree(demo_store_path, repo_root_path)

    composer_json_path = repo_root_path / "app/code/Vendor/Module/composer.json"
    composer_json_path.write_text(
        composer_json_path.read_text().replace(
            '"name": "vendor/module-sample",', '"name": "vendor/module-sample",\n    "version": "1.5.0",'
        ),
        encoding="utf-8",
    )

    repo_root = str(repo_root_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    assert module.setup_version == "1.5.0"
