import shutil
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models import (
    ConfigField,
    CronJob,
    DbTable,
    DiPlugin,
    DiPreference,
    DiVirtualType,
    EventObserver,
    FileHash,
    GraphQlField,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
    QueueBinding,
    WebapiRoute,
)
from app.scanner.dto import QualityFinding
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
async def test_scan_repository_skips_file_hash_dependent_checks_on_a_no_op_rescan(
    demo_store_path: Path, db_session, monkeypatch
):
    """Real-world motivation: a 751-module store's nightly cron was hammering
    php-analyzer non-stop because PHPStan/PHPMD/phpcs/Rector reran for every
    module on every scan, even when nothing in that module's own files had
    changed -- their result can't have changed either in that case. Checks that
    depend on external data (security advisories here) must still rerun every
    time regardless, since that data can change independently of this module's
    own code.
    """
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    php_static_calls = 0
    security_advisory_calls = 0

    async def fake_php_static(*args, **kwargs):
        nonlocal php_static_calls
        php_static_calls += 1
        return []

    async def fake_security_advisories(*args, **kwargs):
        nonlocal security_advisory_calls
        security_advisory_calls += 1
        return []

    monkeypatch.setattr("app.scanner.orchestrator.check_php_static_analysis", fake_php_static)
    monkeypatch.setattr("app.scanner.orchestrator.check_security_advisories", fake_security_advisories)

    await scan_repository(repo_root, db_session)
    assert php_static_calls == 1
    assert security_advisory_calls == 1

    # Re-scan with no changes at all.
    await scan_repository(repo_root, db_session)
    assert php_static_calls == 1  # not called again -- nothing about the module's files changed
    assert security_advisory_calls == 2  # always rechecked -- advisory data can change independently


@pytest.mark.asyncio
async def test_scan_repository_preserves_phpmetrics_findings_on_a_no_op_rescan(
    demo_store_path: Path, db_session, monkeypatch
):
    """Regression test: _FILE_HASH_DEPENDENT_CHECK_TYPES originally listed
    phpstan_error/phpmd_issue/phpcs_violation/php_compat_issue but not
    phpmetrics_issue (added later, in the same check_php_static_analysis
    call) -- a no-op rescan's early cleanup deletes every finding whose
    check_type isn't in that tuple, while the later skip of
    check_php_static_analysis itself means phpmetrics_issue findings were
    never recomputed to replace them. Net effect: a module's phpmetrics_issue
    findings were silently wiped on the very first no-op rescan after they
    were created, and never came back until the module's files changed again.
    """
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    async def fake_php_static(*args, **kwargs):
        return [
            QualityFinding(
                check_type="phpmetrics_issue",
                severity="warning",
                file_path="Foo.php",
                line=None,
                message="Too complex method",
            )
        ]

    monkeypatch.setattr("app.scanner.orchestrator.check_php_static_analysis", fake_php_static)

    await scan_repository(repo_root, db_session)
    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "phpmetrics_issue"
            )
        )
    ).all()
    assert len(findings) == 1

    # Re-scan with no changes at all -- the phpmetrics_issue finding must survive.
    await scan_repository(repo_root, db_session)
    findings_after_rescan = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "phpmetrics_issue"
            )
        )
    ).all()
    assert len(findings_after_rescan) == 1


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
async def test_scan_repository_persists_di_virtual_types(demo_store_path: Path, db_session):
    # <virtualType> was previously invisible — only <preference>/<plugin> were
    # parsed from the same di.xml.
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    virtual_types = (
        await db_session.scalars(select(DiVirtualType).where(DiVirtualType.module_id == module.id))
    ).all()

    assert len(virtual_types) == 1
    assert virtual_types[0].name == "Vendor\\Module\\SampleCollectionFactory"
    assert virtual_types[0].virtual_type == "Vendor\\Module\\Model\\ResourceModel\\Sample\\CollectionFactory"


@pytest.mark.asyncio
async def test_scan_repository_persists_cron_jobs(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    crontab_path = repo_copy / "app/code/Vendor/Module/etc/crontab.xml"
    crontab_path.write_text(
        '<?xml version="1.0"?>\n'
        '<config><group id="default">'
        '<job name="vendor_module_sample_job" instance="Vendor\\Module\\Cron\\SampleJob" method="execute">'
        "<schedule>0 2 * * *</schedule></job>"
        "</group></config>",
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    jobs = (await db_session.scalars(select(CronJob).where(CronJob.module_id == module.id))).all()

    assert len(jobs) == 1
    assert jobs[0].job_name == "vendor_module_sample_job"
    assert jobs[0].instance_class == "Vendor\\Module\\Cron\\SampleJob"
    assert jobs[0].schedule == "0 2 * * *"

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    jobs_after_rescan = (await db_session.scalars(select(CronJob).where(CronJob.module_id == module.id))).all()
    assert len(jobs_after_rescan) == 1


@pytest.mark.asyncio
async def test_scan_repository_persists_webapi_routes(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    webapi_path = repo_copy / "app/code/Vendor/Module/etc/webapi.xml"
    webapi_path.write_text(
        '<?xml version="1.0"?>\n'
        '<routes><route url="/V1/vendor-module/samples" method="GET">'
        '<service class="Vendor\\Module\\Api\\SampleRepositoryInterface" method="getList"/>'
        '<resources><resource ref="Vendor_Module::samples"/></resources>'
        "</route></routes>",
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    routes = (await db_session.scalars(select(WebapiRoute).where(WebapiRoute.module_id == module.id))).all()

    assert len(routes) == 1
    assert routes[0].url == "/V1/vendor-module/samples"
    assert routes[0].service_class == "Vendor\\Module\\Api\\SampleRepositoryInterface"
    assert routes[0].acl_resource == "Vendor_Module::samples"

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    routes_after_rescan = (
        await db_session.scalars(select(WebapiRoute).where(WebapiRoute.module_id == module.id))
    ).all()
    assert len(routes_after_rescan) == 1


@pytest.mark.asyncio
async def test_scan_repository_persists_config_fields(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    system_xml_dir = repo_copy / "app/code/Vendor/Module/etc/adminhtml"
    system_xml_dir.mkdir(parents=True, exist_ok=True)
    (system_xml_dir / "system.xml").write_text(
        '<?xml version="1.0"?>\n'
        "<config><system>"
        '<section id="vendor_module"><label>Vendor Module</label>'
        '<group id="general"><label>General</label>'
        '<field id="enabled" type="select"><label>Enabled</label></field>'
        "</group></section>"
        "</system></config>",
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    fields = (await db_session.scalars(select(ConfigField).where(ConfigField.module_id == module.id))).all()

    assert len(fields) == 1
    assert fields[0].section_id == "vendor_module"
    assert fields[0].group_id == "general"
    assert fields[0].field_id == "enabled"
    assert fields[0].label == "Enabled"

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    fields_after_rescan = (
        await db_session.scalars(select(ConfigField).where(ConfigField.module_id == module.id))
    ).all()
    assert len(fields_after_rescan) == 1


@pytest.mark.asyncio
async def test_scan_repository_persists_db_tables(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    db_schema_path = repo_copy / "app/code/Vendor/Module/etc/db_schema.xml"
    db_schema_path.write_text(
        '<?xml version="1.0"?>\n'
        '<schema xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<table name="vendor_module_sample" comment="Sample table">'
        '<column xsi:type="int" name="entity_id"/>'
        '<column xsi:type="varchar" name="name"/>'
        "</table></schema>",
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    tables = (await db_session.scalars(select(DbTable).where(DbTable.module_id == module.id))).all()

    assert len(tables) == 1
    assert tables[0].table_name == "vendor_module_sample"
    assert tables[0].comment == "Sample table"
    assert tables[0].column_count == 2

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    tables_after_rescan = (await db_session.scalars(select(DbTable).where(DbTable.module_id == module.id))).all()
    assert len(tables_after_rescan) == 1


@pytest.mark.asyncio
async def test_scan_repository_persists_queue_bindings(demo_store_path: Path, db_session, tmp_path: Path):
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    etc_dir = repo_copy / "app/code/Vendor/Module/etc"
    (etc_dir / "communication.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<config><topic name="vendor.module.sample.dispatch" is_synchronous="false" request="string">'
        '<handler name="h" type="Vendor\\Module\\Model\\Queue\\SampleConsumer" method="execute"/>'
        "</topic></config>",
        encoding="utf-8",
    )
    (etc_dir / "queue_topology.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<config><exchange name="magento">'
        '<binding id="X" topic="vendor.module.sample.dispatch" destination="vendor.module.sample.dispatch"/>'
        "</exchange></config>",
        encoding="utf-8",
    )
    (etc_dir / "queue_consumer.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<config><consumer name="vendor.module.sample.dispatch" queue="vendor.module.sample.dispatch" '
        'handler="Vendor\\Module\\Model\\Queue\\SampleConsumer::execute"/></config>',
        encoding="utf-8",
    )

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    bindings = (
        await db_session.scalars(select(QueueBinding).where(QueueBinding.module_id == module.id))
    ).all()

    assert len(bindings) == 1
    assert bindings[0].topic == "vendor.module.sample.dispatch"
    assert bindings[0].consumer_name == "vendor.module.sample.dispatch"
    assert bindings[0].handler_class == "Vendor\\Module\\Model\\Queue\\SampleConsumer"

    # Re-scan with no changes: delete-then-reinsert must not duplicate rows.
    await scan_repository(repo_root, db_session)
    bindings_after_rescan = (
        await db_session.scalars(select(QueueBinding).where(QueueBinding.module_id == module.id))
    ).all()
    assert len(bindings_after_rescan) == 1


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
