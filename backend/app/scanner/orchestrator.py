from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ComposerPackageRequirement,
    DiPlugin,
    DiPreference,
    EventObserver,
    FileAnalysis,
    FileHash,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
    PhpClassMethod,
)
from app.scanner.abandoned_dependencies import check_abandoned_outdated
from app.scanner.composer_json import composer_completeness_findings, parse_composer_json
from app.scanner.config_php import parse_config_php
from app.scanner.deprecated_scanner import scan_deprecated_annotations
from app.scanner.di_xml import parse_di_xml
from app.scanner.discovery import find_modules
from app.scanner.dto import DiscoveredModule, PendingAnalysisJob
from app.scanner.events_xml import parse_events_xml
from app.scanner.hashing import aggregate_hash, compute_module_file_hashes, diff_file_hashes
from app.scanner.magento_upgrade import check_magento_upgrade_readiness
from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml
from app.scanner.php_analyzer_client import check_php_static_analysis
from app.scanner.php_classes import catalog_module_classes
from app.scanner.readme_check import has_readme
from app.scanner.secrets_scanner import scan_hardcoded_secrets
from app.scanner.security_advisories import check_security_advisories
from app.scanner.test_presence import has_tests
from app.tasks.queue import get_arq_pool


class ScanAlreadyInProgressError(RuntimeError):
    """Raised when another scan of the same repo_root is already running."""


@dataclass
class ModuleScanOutcome:
    name: str
    status: str  # "created" | "updated" | "error"
    state: str = "pending"
    classes: int = 0
    plugins: int = 0
    observers: int = 0
    files_added: int = 0
    files_changed: int = 0
    files_removed: int = 0
    warnings: list[str] = field(default_factory=list)
    module_id: int | None = None
    module_current_hash: str | None = None
    pending_file_count: int = 0


@dataclass
class ScanResult:
    repo_root: str
    modules_found: int = 0
    modules_created: int = 0
    modules_updated: int = 0
    classes_total: int = 0
    plugins_total: int = 0
    observers_total: int = 0
    tasks_enqueued: int = 0
    warnings: list[str] = field(default_factory=list)
    modules: list[ModuleScanOutcome] = field(default_factory=list)


@dataclass
class _ParsedModule:
    discovered: DiscoveredModule
    module_xml: object
    composer: object
    di: object
    events: list


async def scan_repository(repo_root: str, session: AsyncSession) -> ScanResult:
    root = Path(repo_root).resolve()

    lock_acquired = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:repo_root, 0))"),
        {"repo_root": str(root)},
    )
    if not lock_acquired:
        raise ScanAlreadyInProgressError(f"a scan of {root} is already in progress")

    result = ScanResult(repo_root=str(root))

    discovered = find_modules(root)
    result.modules_found = len(discovered)

    config_map = parse_config_php(root / "app" / "etc" / "config.php")

    # Phase A: parse module.xml/composer.json/di.xml/events.xml for every module,
    # and build global plugin/observer class sets — a plugin's class can live in
    # a different module than the one declaring it in di.xml.
    parsed: list[_ParsedModule] = []
    all_plugin_classes: set[str] = set()
    all_observer_classes: set[str] = set()

    for d in discovered:
        try:
            module_xml = parse_module_xml(d.root / "etc" / "module.xml")
        except InvalidModuleXmlError as exc:
            result.warnings.append(f"{d.relative_path}: {exc}")
            continue

        composer = parse_composer_json(d.root / "composer.json")
        di = parse_di_xml(d.root / "etc" / "di.xml")
        events = parse_events_xml(d.root / "etc" / "events.xml")

        parsed.append(_ParsedModule(discovered=d, module_xml=module_xml, composer=composer, di=di, events=events))
        all_plugin_classes.update(p.plugin_class for p in di.plugins)
        all_observer_classes.update(e.observer_class for e in events)

    # Phase B: catalog PHP classes, diff file hashes, and persist each module in
    # its own savepoint. Job specs are only merged into pending_jobs once a
    # module's savepoint succeeds, so a rolled-back module never contributes jobs.
    pending_jobs: list[PendingAnalysisJob] = []

    for pm in parsed:
        outcome = ModuleScanOutcome(name=pm.module_xml.name, status="updated")
        module_job_specs: list[PendingAnalysisJob] = []
        try:
            async with session.begin_nested():
                await _persist_module(
                    session, root, pm, config_map, all_plugin_classes, all_observer_classes, outcome, module_job_specs
                )
            pending_jobs.extend(module_job_specs)
        except Exception as exc:  # noqa: BLE001 - one module's failure must not abort the scan
            outcome.status = "error"
            outcome.warnings.append(str(exc))

        if outcome.status == "created":
            result.modules_created += 1
        elif outcome.status == "updated":
            result.modules_updated += 1
        result.classes_total += outcome.classes
        result.plugins_total += outcome.plugins
        result.observers_total += outcome.observers
        result.modules.append(outcome)

    # A removal-only diff (files deleted, nothing added/changed) leaves
    # pending_file_count at 0 with no analyze_file job to ever decrement it to
    # 0 and trigger synthesize_module — enqueue synthesize_module directly for
    # these so the module doc gets regenerated and stale chunks for the
    # deleted files get purged (embed_chunks rebuilds a module's chunks from
    # scratch every run) instead of the module staying stuck in "pending" forever.
    synthesize_only = [
        outcome
        for outcome in result.modules
        if outcome.status != "error" and outcome.state == "pending" and outcome.pending_file_count == 0
    ]

    await session.commit()

    # Only enqueue jobs after the scan's commit has succeeded — a job must never
    # reference module/file state that didn't actually get persisted.
    if pending_jobs:
        pool = await get_arq_pool()
        for job in pending_jobs:
            job_id = f"analyze:{job.module_id}:{job.relative_path}:{job.content_hash}"
            await pool.enqueue_job(
                "analyze_file",
                job.module_id,
                job.relative_path,
                job.content_hash,
                job.module_current_hash,
                _job_id=job_id,
            )
    if synthesize_only:
        pool = await get_arq_pool()
        for outcome in synthesize_only:
            await pool.enqueue_job(
                "synthesize_module",
                outcome.module_id,
                outcome.module_current_hash,
                _job_id=f"synthesize:{outcome.module_id}:{outcome.module_current_hash}",
            )
    result.tasks_enqueued = len(pending_jobs)

    return result


async def _persist_module(
    session: AsyncSession,
    repo_root: Path,
    pm: _ParsedModule,
    config_map: dict[str, bool] | None,
    all_plugin_classes: set[str],
    all_observer_classes: set[str],
    outcome: ModuleScanOutcome,
    job_specs: list[PendingAnalysisJob],
) -> None:
    name = pm.module_xml.name
    existing = await session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == name)
    )

    if existing is not None:
        old_hash_rows = (await session.scalars(select(FileHash).where(FileHash.module_id == existing.id))).all()
        old_hashes = {fh.relative_path: fh.content_hash for fh in old_hash_rows}
        old_analyzed = {fh.relative_path: fh.analyzed for fh in old_hash_rows}
    else:
        old_hashes = {}
        old_analyzed = {}

    new_hashes = compute_module_file_hashes(pm.discovered.root)
    diff = diff_file_hashes(old_hashes, new_hashes)
    new_current_hash = aggregate_hash(new_hashes)

    outcome.files_added = len(diff.added)
    outcome.files_changed = len(diff.changed)
    outcome.files_removed = len(diff.removed)

    enabled = config_map.get(name) if config_map is not None else None
    now = datetime.now(UTC)

    if existing is None:
        module = Module(
            repo_root=str(repo_root),
            name=name,
            path=str(pm.discovered.relative_path),
            source_type=pm.discovered.source_type,
        )
        session.add(module)
        outcome.status = "created"
    else:
        module = existing
        module.path = str(pm.discovered.relative_path)
        module.source_type = pm.discovered.source_type
        outcome.status = "updated"
        await session.execute(delete(ModuleDependency).where(ModuleDependency.module_id == module.id))
        await session.execute(delete(PhpClass).where(PhpClass.module_id == module.id))
        await session.execute(delete(DiPreference).where(DiPreference.module_id == module.id))
        await session.execute(delete(DiPlugin).where(DiPlugin.module_id == module.id))
        await session.execute(delete(EventObserver).where(EventObserver.module_id == module.id))
        await session.execute(delete(FileHash).where(FileHash.module_id == module.id))
        await session.execute(delete(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module.id))
        await session.execute(
            delete(ComposerPackageRequirement).where(ComposerPackageRequirement.module_id == module.id)
        )
        if diff.removed:
            await session.execute(
                delete(FileAnalysis).where(
                    FileAnalysis.module_id == module.id, FileAnalysis.relative_path.in_(diff.removed)
                )
            )

    module.setup_version = pm.module_xml.setup_version
    module.composer_name = pm.composer.name if pm.composer else None
    module.composer_type = pm.composer.type if pm.composer else None
    module.license = pm.composer.license if pm.composer else None
    module.has_readme = has_readme(pm.discovered.root)
    module.has_tests = has_tests(pm.discovered.root)
    module.enabled = enabled
    module.last_scanned_at = now
    module.scan_warnings = list(outcome.warnings)
    module.current_hash = new_current_hash

    if not diff.is_empty():
        module.state = "pending"
        module.pending_file_count = len(diff.added) + len(diff.changed)
    outcome.state = module.state

    await session.flush()  # assign module.id for new rows
    outcome.module_id = module.id
    outcome.module_current_hash = new_current_hash
    outcome.pending_file_count = module.pending_file_count or 0

    added_or_changed = set(diff.added) | set(diff.changed)
    for relative_path, content_hash in new_hashes.items():
        # An added/changed file always starts unanalyzed. An unchanged file
        # carries forward whatever its *actual* previous analyzed status was
        # — it may still be False if a prior analyze_file job was paused on
        # budget and never completed; assuming True just because the content
        # didn't change this scan would drop it from budget-resume requeueing
        # forever (see cli.py's _run_resume_budget, which only requeues
        # FileHash.analyzed.is_(False)).
        analyzed = False if relative_path in added_or_changed else old_analyzed.get(relative_path, False)
        session.add(
            FileHash(
                module_id=module.id,
                relative_path=relative_path,
                content_hash=content_hash,
                analyzed=analyzed,
            )
        )

    for relative_path in diff.added + diff.changed:
        job_specs.append(
            PendingAnalysisJob(
                module_id=module.id,
                relative_path=relative_path,
                content_hash=new_hashes[relative_path],
                module_current_hash=new_current_hash,
            )
        )

    for dep_name in pm.module_xml.sequence:
        session.add(ModuleDependency(module_id=module.id, depends_on_name=dep_name))

    for pref in pm.di.preferences:
        session.add(DiPreference(module_id=module.id, for_type=pref.for_type, preference_type=pref.preference_type))

    for plugin in pm.di.plugins:
        session.add(
            DiPlugin(
                module_id=module.id,
                intercepted_type=plugin.intercepted_type,
                plugin_name=plugin.plugin_name,
                plugin_class=plugin.plugin_class,
                sort_order=plugin.sort_order,
                disabled=plugin.disabled,
            )
        )
    outcome.plugins = len(pm.di.plugins)

    for obs in pm.events:
        session.add(
            EventObserver(
                module_id=module.id,
                event_name=obs.event_name,
                observer_name=obs.observer_name,
                observer_class=obs.observer_class,
                disabled=obs.disabled,
            )
        )
    outcome.observers = len(pm.events)

    classes = catalog_module_classes(pm.discovered.root)
    outcome.classes = len(classes)

    for entry in classes:
        top_level_dir = entry.file_path.split("/", 1)[0]
        in_plugin_dir = top_level_dir == "Plugin"
        in_observer_dir = top_level_dir == "Observer"
        xml_plugin = entry.fqcn in all_plugin_classes
        xml_observer = entry.fqcn in all_observer_classes

        role_signals = []
        if in_plugin_dir or in_observer_dir:
            role_signals.append("directory_convention")
        if xml_plugin:
            role_signals.append("di_xml_plugin")
        if xml_observer:
            role_signals.append("events_xml_observer")

        is_plugin = in_plugin_dir or xml_plugin
        is_observer = in_observer_dir or xml_observer

        php_class = PhpClass(
            module_id=module.id,
            fqcn=entry.fqcn,
            namespace=entry.namespace,
            class_name=entry.class_name,
            kind=entry.kind,
            extends=entry.extends or None,
            implements=entry.implements or None,
            file_path=entry.file_path,
            start_line=entry.start_line,
            end_line=entry.end_line,
            is_plugin=is_plugin,
            is_observer=is_observer,
            role_signals=role_signals,
        )
        session.add(php_class)

        if is_plugin or is_observer:
            await session.flush()  # assign php_class.id
            for m in entry.methods:
                session.add(
                    PhpClassMethod(
                        class_id=php_class.id, name=m.name, start_line=m.start_line, end_line=m.end_line
                    )
                )

    requirements = pm.composer.requirements if pm.composer else {}
    dev_requirements = pm.composer.dev_requirements if pm.composer else {}
    all_requirements = {**requirements, **dev_requirements}

    for package_name, package_constraint in requirements.items():
        session.add(
            ComposerPackageRequirement(
                module_id=module.id, package_name=package_name, constraint=package_constraint, is_dev=False
            )
        )
    for package_name, package_constraint in dev_requirements.items():
        session.add(
            ComposerPackageRequirement(
                module_id=module.id, package_name=package_name, constraint=package_constraint, is_dev=True
            )
        )

    quality_findings = [
        *composer_completeness_findings(pm.composer),
        *scan_deprecated_annotations(pm.discovered.root),
        *scan_hardcoded_secrets(pm.discovered.root),
        *await check_security_advisories(session, all_requirements),
        *await check_abandoned_outdated(session, all_requirements),
        *await check_php_static_analysis(pm.discovered.root),
        *await check_magento_upgrade_readiness(
            session, pm.composer.php_constraint if pm.composer else None, all_requirements
        ),
    ]
    for finding in quality_findings:
        session.add(
            ModuleQualityFinding(
                module_id=module.id,
                check_type=finding.check_type,
                severity=finding.severity,
                file_path=finding.file_path,
                line=finding.line,
                message=finding.message,
            )
        )
