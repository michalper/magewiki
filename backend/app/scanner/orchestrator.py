import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine
from app.models import (
    ComposerPackageRequirement,
    DiPlugin,
    DiPreference,
    EventObserver,
    FileAnalysis,
    FileHash,
    GraphQlField,
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
from app.scanner.dto import (
    ComposerResult,
    DiscoveredModule,
    DiXmlResult,
    EventObserverEntry,
    GraphQlFieldEntry,
    ModuleXmlResult,
    PendingAnalysisJob,
)
from app.scanner.events_xml import parse_events_xml
from app.scanner.graphql_schema import parse_graphql_schema
from app.scanner.hashing import aggregate_hash, compute_module_file_hashes, diff_file_hashes
from app.scanner.installed_versions import parse_installed_versions
from app.scanner.magento_upgrade import check_magento_upgrade_readiness
from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml
from app.scanner.multi_store import find_store_roots
from app.scanner.php_analyzer_client import check_php_static_analysis
from app.scanner.php_classes import catalog_module_classes
from app.scanner.readme_check import has_readme
from app.scanner.secrets_scanner import scan_hardcoded_secrets
from app.scanner.security_advisories import check_security_advisories
from app.scanner.test_presence import has_tests
from app.tasks.queue import get_arq_pool

logger = logging.getLogger(__name__)


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
    stores_scanned: int = 1


@dataclass
class _ParsedModule:
    discovered: DiscoveredModule
    module_xml: ModuleXmlResult
    composer: ComposerResult | None
    di: DiXmlResult
    events: list[EventObserverEntry]
    graphql: list[GraphQlFieldEntry]


async def scan_repository(repo_root: str, session: AsyncSession) -> ScanResult:
    """Non-streaming callers (cron, webhook, CLI, evaluation) — drains
    scan_repository_events() and returns just the final result, same contract
    as before this function grew live progress events.
    """
    result: ScanResult | None = None
    async for event in scan_repository_events(repo_root, session):
        if event["event"] == "done":
            result = event["result"]
    assert result is not None  # "done" is always the generator's last event
    return result


async def scan_paths(path: str, session: AsyncSession) -> ScanResult:
    """Non-streaming counterpart to scan_paths_events(), same drain pattern as
    scan_repository().
    """
    result: ScanResult | None = None
    async for event in scan_paths_events(path, session):
        if event["event"] == "done":
            result = event["result"]
    assert result is not None  # "done" is always the generator's last event
    return result


async def scan_paths_events(path: str, session: AsyncSession) -> AsyncIterator[dict]:
    """Expands `path` into one or more store/module roots (find_store_roots)
    and scans each in turn — a directory containing several stores side by
    side (e.g. /sites/store-a, /sites/store-b, ...) scans all of them in one
    operation instead of requiring one POST /scan per store. Delegates
    straight to scan_repository_events() unchanged whenever `path` resolves
    to zero or one roots, so every existing single-store call site (cron,
    webhook, CLI, evaluation — none of which call this new function anyway,
    only the interactive POST /scan[/stream] routes do) keeps behaving
    identically; this function is additive, not a replacement.
    """
    roots = find_store_roots(Path(path).resolve())
    if len(roots) <= 1:
        async for event in scan_repository_events(path, session):
            yield event
        return

    combined = ScanResult(repo_root=path, stores_scanned=len(roots))
    for index, root in enumerate(roots, start=1):
        yield {"event": "store", "name": root.name, "index": index, "total": len(roots)}
        async for event in scan_repository_events(str(root), session):
            if event["event"] == "done":
                store_result: ScanResult = event["result"]
                combined.modules_found += store_result.modules_found
                combined.modules_created += store_result.modules_created
                combined.modules_updated += store_result.modules_updated
                combined.classes_total += store_result.classes_total
                combined.plugins_total += store_result.plugins_total
                combined.observers_total += store_result.observers_total
                combined.tasks_enqueued += store_result.tasks_enqueued
                combined.warnings.extend(f"[{root.name}] {w}" for w in store_result.warnings)
                combined.modules.extend(store_result.modules)
            else:
                yield event
    yield {"event": "done", "result": combined}


async def scan_repository_events(repo_root: str, session: AsyncSession) -> AsyncIterator[dict]:
    """The actual scan — a generator so a streaming caller (POST /scan/stream)
    can show live progress. Commits per module rather than once at the end
    specifically so that progress is real: a module is only visible to any
    other query (including the UI's own) once its own commit lands, not when
    the whole scan finishes. That rules out the transaction-scoped advisory
    lock this used before (pg_try_advisory_xact_lock releases at the first
    commit) — pg_try_advisory_lock/pg_advisory_unlock is session-scoped
    instead, held for the generator's whole lifetime regardless of how many
    commits happen in between, and auto-released by Postgres if the
    connection terminates uncleanly.
    """
    root = Path(repo_root).resolve()
    lock_key = {"repo_root": str(root)}

    # A session-level advisory lock is tied to one specific physical
    # connection — but AsyncSession checks out a *new* connection from the
    # pool for each transaction it begins (autobegin after every commit()),
    # and this generator commits once per module. Acquiring the lock through
    # `session` and releasing it through `session` later is therefore not
    # reliably the same connection: pg_advisory_unlock silently returns
    # false (lock not actually held by the caller) and the lock leaks onto
    # whatever connection originally acquired it, now idle in the pool.
    # Confirmed empirically (debug logging on a real failing test run) before
    # this fix. A connection obtained directly from the engine is pinned to
    # one physical connection for its whole scope, unlike a Session — use
    # that, dedicated solely to the lock, independent of whatever connections
    # `session` itself churns through for the actual scan work.
    async with engine.connect() as lock_connection:
        lock_acquired = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:repo_root, 0))"), lock_key
        )
        if not lock_acquired:
            raise ScanAlreadyInProgressError(f"a scan of {root} is already in progress")

        try:
            async for event in _run_scan(root, session):
                yield event
        finally:
            await lock_connection.scalar(
                text("SELECT pg_advisory_unlock(hashtextextended(:repo_root, 0))"), lock_key
            )


async def _run_scan(root: Path, session: AsyncSession) -> AsyncIterator[dict]:
    result = ScanResult(repo_root=str(root))

    discovered = find_modules(root)
    result.modules_found = len(discovered)
    yield {"event": "discovered", "total": len(discovered)}

    config_map = parse_config_php(root / "app" / "etc" / "config.php")
    installed_versions = parse_installed_versions(root)

    # Phase A: parse module.xml/composer.json/di.xml/events.xml for every module,
    # and build global plugin/observer class sets — a plugin's class can live in
    # a different module than the one declaring it in di.xml. This has to finish
    # for every module before Phase B persists any of them, so it can't be folded
    # into one per-module pass.
    parsed: list[_ParsedModule] = []
    all_plugin_classes: set[str] = set()
    all_observer_classes: set[str] = set()
    processed = 0

    for d in discovered:
        try:
            module_xml = parse_module_xml(d.root / "etc" / "module.xml")
        except InvalidModuleXmlError as exc:
            message = f"{d.relative_path}: {exc}"
            result.warnings.append(message)
            processed += 1
            yield {
                "event": "module",
                "name": str(d.relative_path),
                "status": "error",
                "index": processed,
                "total": len(discovered),
                "warning": message,
            }
            continue

        try:
            composer = parse_composer_json(d.root / "composer.json")
            di = parse_di_xml(d.root / "etc" / "di.xml")
            events = parse_events_xml(d.root / "etc" / "events.xml")
            graphql = parse_graphql_schema(d.root / "etc" / "schema.graphqls")
        except OSError as exc:
            # Each parser already checks .is_file() before reading, but a
            # permission error or a race (file removed/replaced between that
            # check and the read) still raises OSError uncaught — without this,
            # it would abort scanning every remaining module in the store, not
            # just this one (unlike module_xml's own try/except above, scoped
            # per-module from the start).
            message = f"{d.relative_path}: {exc}"
            result.warnings.append(message)
            processed += 1
            yield {
                "event": "module",
                "name": str(d.relative_path),
                "status": "error",
                "index": processed,
                "total": len(discovered),
                "warning": message,
            }
            continue

        parsed.append(
            _ParsedModule(
                discovered=d, module_xml=module_xml, composer=composer, di=di, events=events, graphql=graphql
            )
        )
        all_plugin_classes.update(p.plugin_class for p in di.plugins)
        all_observer_classes.update(e.observer_class for e in events)

    # Phase B: catalog PHP classes, diff file hashes, and persist each module in
    # its own savepoint, committing immediately after — so it's visible to any
    # other query right away, and so one module's quality-check calls (real HTTP
    # to php-analyzer/Packagist/GitHub) don't gate visibility of every module
    # scanned before it.
    tasks_enqueued = 0

    for pm in parsed:
        outcome = ModuleScanOutcome(name=pm.module_xml.name, status="updated")
        module_job_specs: list[PendingAnalysisJob] = []
        try:
            async with session.begin_nested():
                await _persist_module(
                    session,
                    root,
                    pm,
                    config_map,
                    installed_versions,
                    all_plugin_classes,
                    all_observer_classes,
                    outcome,
                    module_job_specs,
                )
            await session.commit()
        except Exception as exc:
            outcome.status = "error"
            message = f"{pm.module_xml.name}: {exc}"
            outcome.warnings.append(message)
            # A per-module failure was previously only visible on
            # ModuleScanOutcome.warnings, which the UI never renders — only
            # the scan-level ScanResult.warnings list is shown, so a scan
            # where every module fails looked like a silent "0 created, 0
            # updated" success instead of a clear error. Surface it at both
            # levels, and log the full traceback server-side since str(exc)
            # alone can be uninformative for some exception types.
            result.warnings.append(message)
            logger.exception("scan_repository: failed to persist module %s", pm.module_xml.name)
            module_job_specs = []

        if outcome.status == "created":
            result.modules_created += 1
        elif outcome.status == "updated":
            result.modules_updated += 1
        result.classes_total += outcome.classes
        result.plugins_total += outcome.plugins
        result.observers_total += outcome.observers
        result.modules.append(outcome)

        # Only enqueue jobs after this module's own commit has succeeded — a
        # job must never reference module/file state that didn't actually
        # get persisted.
        if module_job_specs:
            pool = await get_arq_pool()
            for job in module_job_specs:
                job_id = f"analyze:{job.module_id}:{job.relative_path}:{job.content_hash}"
                await pool.enqueue_job(
                    "analyze_file", job.module_id, job.relative_path, job.content_hash, job.module_current_hash,
                    _job_id=job_id,
                )
            tasks_enqueued += len(module_job_specs)

        # A removal-only diff (files deleted, nothing added/changed) leaves
        # pending_file_count at 0 with no analyze_file job to ever decrement
        # it to 0 and trigger synthesize_module — enqueue synthesize_module
        # directly so the module doc gets regenerated and stale chunks for
        # the deleted files get purged (embed_chunks rebuilds a module's
        # chunks from scratch every run) instead of the module staying stuck
        # in "pending" forever.
        if outcome.status != "error" and outcome.state == "pending" and outcome.pending_file_count == 0:
            pool = await get_arq_pool()
            await pool.enqueue_job(
                "synthesize_module",
                outcome.module_id,
                outcome.module_current_hash,
                _job_id=f"synthesize:{outcome.module_id}:{outcome.module_current_hash}",
            )

        processed += 1
        yield {
            "event": "module",
            "name": outcome.name,
            "status": outcome.status,
            "index": processed,
            "total": len(discovered),
            "warning": outcome.warnings[0] if outcome.warnings else None,
        }

    result.tasks_enqueued = tasks_enqueued
    yield {"event": "done", "result": result}


_ModuleChildModel = type[DiPreference] | type[DiPlugin] | type[EventObserver] | type[GraphQlField]


async def _sync_module_children(
    session: AsyncSession, module_id: int, model_cls: _ModuleChildModel, entries: list
) -> None:
    """Replace every row of model_cls for this module — delete, then reinsert from
    freshly parsed entries. Shared by every 1:N parsed-fact table whose DTO field
    names already match the model's column names exactly (DiPreference, DiPlugin,
    EventObserver, GraphQlField) — a single, always-correct code path instead of a
    hand-maintained delete() + insert-loop pair per entity type (4 near-identical
    copies before this), which can desync as new fact types are added. This
    project already hit exactly that class of bug once (e9ed07a's pending_file_count
    desync, caused by a forgotten reset in one of several hand-copied code paths).
    Safe to call for a brand-new module too — deleting from an empty set is a no-op.
    """
    await session.execute(delete(model_cls).where(model_cls.module_id == module_id))
    for entry in entries:
        session.add(model_cls(module_id=module_id, **asdict(entry)))


async def _persist_module(
    session: AsyncSession,
    repo_root: Path,
    pm: _ParsedModule,
    config_map: dict[str, bool] | None,
    installed_versions: dict[str, str],
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

    # Reads and SHA256-hashes every file in the module — genuinely blocking disk
    # I/O and CPU work. Calling it directly here would block the whole event loop
    # for the duration, stalling every other concurrent coroutine (other modules'
    # DB work, SSE progress streaming) for as long as this one module's files take
    # to hash, defeating the per-module-commit live-progress design.
    new_hashes = await asyncio.to_thread(compute_module_file_hashes, pm.discovered.root)
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
        # DiPreference/DiPlugin/EventObserver/GraphQlField are deleted together with
        # their reinsertion in _sync_module_children below, not here.
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

    # Composer's version wins over module.xml's setup_version, not just as a
    # fallback for when setup_version is absent — setup_version is an internal
    # Magento upgrade-script trigger, commonly left stale at its initial value
    # for a module's whole lifetime once declarative schema removes the need to
    # ever bump it again (confirmed against two real cases: Amasty_Base has no
    # setup_version attribute at all, and Ordo_Automation's says "0.1.0" even
    # though its composer.json says "1.0.0" — setup_version was simply never
    # touched after the module's very first release). Prefer composer.json's own
    # "version" field (present for both of those real cases) over the Composer-
    # resolved installed.json version (only present for genuinely Composer-
    # installed packages — absent for e.g. a manually vendor-src-synced module),
    # falling back to setup_version only when neither Composer source has one.
    composer_name = pm.composer.name if pm.composer else None
    module.setup_version = (
        (pm.composer.version if pm.composer else None)
        or (installed_versions.get(composer_name) if composer_name else None)
        or pm.module_xml.setup_version
    )
    module.composer_name = composer_name
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

    await _sync_module_children(session, module.id, DiPreference, pm.di.preferences)
    await _sync_module_children(session, module.id, DiPlugin, pm.di.plugins)
    outcome.plugins = len(pm.di.plugins)
    await _sync_module_children(session, module.id, EventObserver, pm.events)
    outcome.observers = len(pm.events)
    await _sync_module_children(session, module.id, GraphQlField, pm.graphql)

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

    async def _session_based_checks() -> list:
        # These three all read/write the same packagist_cache table through the
        # one shared `session` — AsyncSession doesn't support concurrent use
        # from multiple coroutines, so they must stay sequential relative to
        # each other (unlike check_php_static_analysis below, which never
        # touches `session` and is genuinely independent).
        return [
            *await check_security_advisories(session, all_requirements),
            *await check_abandoned_outdated(session, all_requirements),
            *await check_magento_upgrade_readiness(
                session, pm.composer.php_constraint if pm.composer else None, all_requirements
            ),
        ]

    session_findings, php_static_findings = await asyncio.gather(
        _session_based_checks(), check_php_static_analysis(pm.discovered.root)
    )
    quality_findings = [
        *composer_completeness_findings(pm.composer),
        *scan_deprecated_annotations(pm.discovered.root),
        *scan_hardcoded_secrets(pm.discovered.root),
        *session_findings,
        *php_static_findings,
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
