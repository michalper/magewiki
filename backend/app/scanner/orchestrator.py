import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine
from app.models import (
    AclResource,
    ComposerPackageRequirement,
    ConfigField,
    CronJob,
    DbColumn,
    DbTable,
    DiPlugin,
    DiPreference,
    DiVirtualType,
    EventObserver,
    FileAnalysis,
    FileHash,
    GraphQlField,
    Module,
    ModuleDependency,
    ModuleIndexer,
    ModuleMview,
    ModuleQualityFinding,
    ModuleRoute,
    ModuleWidget,
    PhpClass,
    PhpClassMethod,
    QueueBinding,
    WebapiRoute,
)
from app.scanner.abandoned_dependencies import check_abandoned_outdated
from app.scanner.acl_conflicts import AclResourceRow, detect_acl_resource_conflicts
from app.scanner.acl_xml import parse_acl_xml
from app.scanner.admin_acl import find_missing_acl
from app.scanner.alerts import send_quality_alert
from app.scanner.circular_dependencies import ModuleDependencyRow, detect_circular_dependencies
from app.scanner.composer_conflicts import ComposerRequirementRow, detect_composer_conflicts
from app.scanner.composer_json import composer_completeness_findings, parse_composer_json
from app.scanner.config_php import parse_config_php
from app.scanner.cron_conflicts import CronJobRow, detect_cron_job_conflicts
from app.scanner.crontab_xml import parse_crontab_xml
from app.scanner.db_schema_conflicts import DbColumnRow, detect_db_schema_conflicts
from app.scanner.db_schema_xml import parse_db_schema_xml
from app.scanner.deprecated_scanner import scan_deprecated_annotations
from app.scanner.di_xml import parse_di_xml
from app.scanner.discovery import find_modules
from app.scanner.dto import (
    AclResourceEntry,
    ComposerResult,
    ConfigFieldEntry,
    CronJobEntry,
    DbColumnEntry,
    DbTableEntry,
    DiscoveredModule,
    DiXmlResult,
    EventObserverEntry,
    GraphQlFieldEntry,
    IndexerEntry,
    ModuleXmlResult,
    MviewEntry,
    PendingAnalysisJob,
    QueueBindingEntry,
    RouteEntry,
    WebapiRouteEntry,
    WidgetEntry,
)
from app.scanner.events_xml import parse_events_xml
from app.scanner.graphql_conflicts import GraphQlFieldRow, detect_graphql_field_conflicts
from app.scanner.graphql_schema import parse_graphql_schema
from app.scanner.hashing import aggregate_hash, compute_module_file_hashes, diff_file_hashes
from app.scanner.history import write_history_snapshots
from app.scanner.indexer_conflicts import IndexerRow, detect_indexer_conflicts
from app.scanner.indexer_xml import parse_indexer_xml
from app.scanner.installed_versions import parse_installed_versions
from app.scanner.license_check import check_license_risk
from app.scanner.magento_upgrade import check_magento_upgrade_readiness
from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml
from app.scanner.multi_store import find_store_roots
from app.scanner.mview_conflicts import MviewRow, detect_mview_conflicts
from app.scanner.mview_xml import parse_mview_xml
from app.scanner.php_analyzer_client import check_php_static_analysis, check_php_unit_tests
from app.scanner.php_classes import catalog_module_classes
from app.scanner.plugin_conflicts import PluginRow, detect_plugin_conflicts
from app.scanner.preference_conflicts import PreferenceRow, detect_preference_conflicts
from app.scanner.queue_config import parse_queue_config
from app.scanner.readme_check import has_readme
from app.scanner.route_conflicts import (
    RouteRow,
    detect_frontname_conflicts,
    detect_route_id_conflicts,
)
from app.scanner.routes_xml import parse_routes_xml
from app.scanner.secrets_scanner import scan_hardcoded_secrets
from app.scanner.security_advisories import check_security_advisories
from app.scanner.system_xml import parse_system_xml
from app.scanner.test_presence import has_tests
from app.scanner.virtual_type_conflicts import VirtualTypeRow, detect_virtual_type_conflicts
from app.scanner.webapi_conflicts import WebapiRouteRow, detect_webapi_route_conflicts
from app.scanner.webapi_xml import parse_webapi_xml
from app.scanner.widget_conflicts import WidgetRow, detect_widget_id_conflicts
from app.scanner.widget_xml import parse_widget_xml
from app.tasks.queue import get_arq_pool

logger = logging.getLogger(__name__)


class ScanAlreadyInProgressError(RuntimeError):
    """Raised when another scan of the same repo_root is already running."""


# check_types whose result depends only on this module's own files -- safe to
# skip recomputing when diff.is_empty() (see _persist_module). Every other
# check_type (security_advisory, abandoned_dependency, outdated_dependency,
# magento_php_incompatible, magento_version_blocker, plugin_conflict) depends
# on external/fleet-wide data that can change independently of this module's
# own code, so those are never skipped this way.
_FILE_HASH_DEPENDENT_CHECK_TYPES = (
    "composer_completeness",
    "deprecated_annotation",
    "hardcoded_secret",
    "phpstan_error",
    "phpmd_issue",
    "phpcs_violation",
    "php_compat_issue",
    # Added later than the other check_php_static_analysis findings above
    # (PhpMetrics shipped after this tuple did) and originally missed here --
    # see the "phpmetrics_issue findings silently wiped" regression note.
    "phpmetrics_issue",
    # Purely a function of composer.json's own license field, same as
    # composer_completeness above.
    "license_risk",
    # A module's own Test/Unit/ result is purely a function of its own code,
    # same as every check_php_static_analysis finding above -- same reason.
    "phpunit_failure",
    # A module's own Controller/Adminhtml classes and their extends/implements/
    # consts are purely a function of its own PHP files, same reason as
    # deprecated_annotation/hardcoded_secret above.
    "missing_acl",
)


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
    cron_jobs: list[CronJobEntry]
    webapi_routes: list[WebapiRouteEntry]
    config_fields: list[ConfigFieldEntry]
    db_tables: list[DbTableEntry]
    db_columns: list[DbColumnEntry]
    queue_bindings: list[QueueBindingEntry]
    acl_resources: list[AclResourceEntry]
    indexers: list[IndexerEntry]
    mviews: list[MviewEntry]
    routes: list[RouteEntry]
    widgets: list[WidgetEntry]


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
    discovered_roots = find_store_roots(Path(path).resolve())

    # find_store_roots() enumerates path.iterdir() and follows symlinks (Path.is_dir()
    # resolves them) — a child that's a symlink to somewhere outside the configured
    # scan roots would otherwise bypass the one containment check the API layer makes
    # against the top-level requested `path`, since that check never sees these
    # dynamically-discovered children. Re-validate each one here, at the point they're
    # actually expanded, rather than trusting every call site to re-check.
    roots = [root for root in discovered_roots if settings.is_within_scan_roots(str(root))]
    skipped_roots = [root for root in discovered_roots if root not in roots]

    if len(roots) <= 1 and not skipped_roots:
        async for event in scan_repository_events(path, session):
            yield event
        return

    combined = ScanResult(repo_root=path, stores_scanned=len(roots))
    for root in skipped_roots:
        combined.warnings.append(
            f"skipped {root.name}: resolves outside the configured scan roots (possible symlink escape)"
        )
    for index, root in enumerate(roots, start=1):
        yield {"event": "store", "name": root.name, "index": index, "total": len(roots)}
        try:
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
        except ScanAlreadyInProgressError:
            # Same "another trigger got there first, not a failure" treatment
            # every other caller of scan_repository_events/scan_repository
            # gives this exception (jobs.py, the API routes, the CLI) --
            # one locked store (e.g. a concurrent nightly cron run) must not
            # abort the stores that weren't locked and could scan fine.
            combined.warnings.append(f"skipped {root.name}: a scan of this store is already in progress")
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


# A Postgres deadlock (SQLSTATE 40P01) is transient by construction -- see
# the retry loop in _run_scan below. 2 attempts, not more: a deadlock that
# survives one immediate retry is very unlikely to be transient contention
# and more likely a real, persistent lock-ordering problem worth surfacing
# as a real module failure rather than silently retried forever.
_MAX_MODULE_PERSIST_ATTEMPTS = 2


def _is_deadlock(exc: BaseException) -> bool:
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == "40P01"


async def _run_scan(root: Path, session: AsyncSession) -> AsyncIterator[dict]:
    result = ScanResult(repo_root=str(root))

    discovered = find_modules(root)
    result.modules_found = len(discovered)
    yield {"event": "discovered", "total": len(discovered)}

    config_map = parse_config_php(root / "app" / "etc" / "config.php")
    installed_versions = parse_installed_versions(root)

    # Phase A: parse module.xml/composer.json/di.xml/events.xml/crontab.xml for every module,
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
            cron_jobs = parse_crontab_xml(d.root / "etc" / "crontab.xml")
            webapi_routes = parse_webapi_xml(d.root / "etc" / "webapi.xml")
            config_fields = parse_system_xml(d.root / "etc" / "adminhtml" / "system.xml")
            db_tables, db_columns = parse_db_schema_xml(d.root / "etc" / "db_schema.xml")
            queue_bindings = parse_queue_config(
                d.root / "etc" / "communication.xml",
                d.root / "etc" / "queue_topology.xml",
                d.root / "etc" / "queue_consumer.xml",
            )
            acl_resources = parse_acl_xml(d.root / "etc" / "acl.xml")
            indexers = parse_indexer_xml(d.root / "etc" / "indexer.xml")
            mviews = parse_mview_xml(d.root / "etc" / "mview.xml")
            routes = [
                *parse_routes_xml(d.root / "etc" / "frontend" / "routes.xml", "frontend"),
                *parse_routes_xml(d.root / "etc" / "adminhtml" / "routes.xml", "adminhtml"),
            ]
            widgets = [
                *parse_widget_xml(d.root / "view" / "base" / "widget.xml"),
                *parse_widget_xml(d.root / "view" / "frontend" / "widget.xml"),
                *parse_widget_xml(d.root / "view" / "adminhtml" / "widget.xml"),
            ]
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
                discovered=d,
                module_xml=module_xml,
                composer=composer,
                di=di,
                events=events,
                graphql=graphql,
                cron_jobs=cron_jobs,
                webapi_routes=webapi_routes,
                config_fields=config_fields,
                db_tables=db_tables,
                db_columns=db_columns,
                queue_bindings=queue_bindings,
                acl_resources=acl_resources,
                indexers=indexers,
                mviews=mviews,
                routes=routes,
                widgets=widgets,
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
        for attempt in range(1, _MAX_MODULE_PERSIST_ATTEMPTS + 1):
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
                break
            except Exception as exc:
                # The savepoint's own __aexit__ already rolled back the
                # savepoint itself on the way out, but a DBAPI-level error
                # (a deadlock in particular -- confirmed directly against a
                # real 751-module store under concurrent scan activity) can
                # leave the session's outer transaction/connection unusable
                # for whatever runs next, surfacing later as an unrelated-
                # looking PendingRollbackError on the *next* module or on
                # Phase C's own advisory-lock release. An explicit
                # session-level rollback here, for every failure not just
                # deadlocks, is what actually clears that -- confirmed this
                # is what the retry below needs to even be able to succeed.
                await session.rollback()
                if _is_deadlock(exc) and attempt < _MAX_MODULE_PERSIST_ATTEMPTS:
                    # A Postgres deadlock is transient by nature -- one of
                    # the two transactions involved is always the one
                    # Postgres picks to abort, and it almost always succeeds
                    # on an immediate retry rather than needing to wait for
                    # the *next whole scan* to self-heal this one module.
                    logger.warning(
                        "scan_repository: deadlock persisting %s, retrying (attempt %d/%d)",
                        pm.module_xml.name,
                        attempt,
                        _MAX_MODULE_PERSIST_ATTEMPTS,
                    )
                    module_job_specs = []
                    continue
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
                break

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

    # Phase C: cross-module plugin-conflict detection. Needs every scanned
    # module's di_plugins *and* php_class_methods already committed (a
    # plugin's class, and therefore which method(s) it actually hooks, can
    # live in a different module than the one declaring the plugin in
    # di.xml — same reason Phase A/B split exists for role-flagging), so
    # this can only run after the per-module loop above, not folded into it.
    # It also recomputes across the *whole* repo_root's already-persisted
    # modules, not just the ones in this scan, so a single-module scan still
    # catches a conflict against a module scanned previously.
    await _detect_and_persist_plugin_conflicts(session, root)
    # Same reasoning as plugin-conflict detection above: needs every scanned
    # module's composer_package_requirements already committed, recomputes
    # across the whole repo_root's already-persisted modules.
    await _detect_and_persist_composer_conflicts(session, root)
    # Same reasoning again: needs every scanned module's webapi_routes
    # already committed, recomputes across the whole repo_root.
    await _detect_and_persist_webapi_route_conflicts(session, root)
    # Same reasoning again: needs every scanned module's db_columns already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_db_schema_conflicts(session, root)
    # Same reasoning again: needs every scanned module's dependencies already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_circular_dependencies(session, root)
    # Same reasoning again: needs every scanned module's di_preferences
    # already committed, recomputes across the whole repo_root.
    await _detect_and_persist_preference_conflicts(session, root)
    # Same reasoning again: needs every scanned module's cron_jobs already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_cron_job_conflicts(session, root)
    # Same reasoning again: needs every scanned module's graphql_fields
    # already committed, recomputes across the whole repo_root.
    await _detect_and_persist_graphql_field_conflicts(session, root)
    # Same reasoning again: needs every scanned module's acl_resources
    # already committed, recomputes across the whole repo_root.
    await _detect_and_persist_acl_resource_conflicts(session, root)
    # Same reasoning again: needs every scanned module's indexers already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_indexer_conflicts(session, root)
    # Same reasoning again: needs every scanned module's mviews already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_mview_conflicts(session, root)
    # Same reasoning again: needs every scanned module's routes already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_route_id_conflicts(session, root)
    await _detect_and_persist_frontname_conflicts(session, root)
    # Same reasoning again: needs every scanned module's di_virtual_types
    # already committed, recomputes across the whole repo_root.
    await _detect_and_persist_virtual_type_conflicts(session, root)
    # Same reasoning again: needs every scanned module's widgets already
    # committed, recomputes across the whole repo_root.
    await _detect_and_persist_widget_id_conflicts(session, root)

    # Phase 16: module history. Runs last, after every conflict check above,
    # since a module's finding_counts aren't complete until cross-module
    # conflicts involving it have been detected and persisted. Phase 18: the
    # same before/after finding_counts comparison already happening there
    # is also exactly what an alert needs, so it returns any alert-worthy
    # increases found along the way instead of a second pass over the data.
    module_alerts = await write_history_snapshots(session, root, settings.alert_check_type_tuple)
    await send_quality_alert(settings.alert_webhook_url, str(root), module_alerts)

    result.tasks_enqueued = tasks_enqueued
    yield {"event": "done", "result": result}


async def _detect_and_persist_plugin_conflicts(session: AsyncSession, root: Path) -> None:
    plugin_rows = (
        await session.execute(
            select(
                DiPlugin.module_id,
                Module.name,
                DiPlugin.intercepted_type,
                DiPlugin.plugin_name,
                DiPlugin.plugin_class,
                DiPlugin.sort_order,
                DiPlugin.disabled,
            )
            .join(Module, Module.id == DiPlugin.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    plugins = [PluginRow(*row) for row in plugin_rows]

    method_rows = (
        await session.execute(
            select(PhpClass.fqcn, PhpClassMethod.name)
            .join(PhpClassMethod, PhpClassMethod.class_id == PhpClass.id)
            .join(Module, Module.id == PhpClass.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    class_methods: dict[str, set[str]] = defaultdict(set)
    for fqcn, method_name in method_rows:
        class_methods[fqcn].add(method_name)

    findings = detect_plugin_conflicts(plugins, class_methods)
    await _persist_conflict_findings(session, root, "plugin_conflict", findings)


async def _detect_and_persist_composer_conflicts(session: AsyncSession, root: Path) -> None:
    requirement_rows = (
        await session.execute(
            select(
                ComposerPackageRequirement.module_id,
                Module.name,
                ComposerPackageRequirement.package_name,
                ComposerPackageRequirement.constraint,
            )
            .join(Module, Module.id == ComposerPackageRequirement.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    requirements = [ComposerRequirementRow(*row) for row in requirement_rows]

    findings = detect_composer_conflicts(requirements)
    await _persist_conflict_findings(session, root, "composer_conflict", findings)


async def _detect_and_persist_webapi_route_conflicts(session: AsyncSession, root: Path) -> None:
    route_rows = (
        await session.execute(
            select(
                WebapiRoute.module_id,
                Module.name,
                WebapiRoute.url,
                WebapiRoute.http_method,
                WebapiRoute.service_class,
                WebapiRoute.service_method,
            )
            .join(Module, Module.id == WebapiRoute.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    routes = [WebapiRouteRow(*row) for row in route_rows]

    findings = detect_webapi_route_conflicts(routes)
    await _persist_conflict_findings(session, root, "webapi_route_conflict", findings)


async def _persist_conflict_findings(
    session: AsyncSession, root: Path, check_type: str, findings: list[tuple[int, Any]]
) -> None:
    """The persistence tail every cross-module conflict check shares: wipe
    this check_type's existing findings for `root`, then insert whatever
    (module_id, QualityFinding) pairs the check's own pure detect function
    returned. Every _detect_and_persist_* function's own fetch query/row
    dataclass/detect function differ; this part never does.
    """
    await session.execute(
        delete(ModuleQualityFinding).where(
            ModuleQualityFinding.check_type == check_type,
            ModuleQualityFinding.module_id.in_(select(Module.id).where(Module.repo_root == str(root))),
        )
    )
    for module_id, finding in findings:
        session.add(
            ModuleQualityFinding(
                module_id=module_id,
                check_type=finding.check_type,
                severity=finding.severity,
                file_path=finding.file_path,
                line=finding.line,
                message=finding.message,
            )
        )
    await session.commit()


async def _detect_and_persist_acl_resource_conflicts(session: AsyncSession, root: Path) -> None:
    resource_rows = (
        await session.execute(
            select(AclResource.module_id, Module.name, AclResource.resource_id)
            .join(Module, Module.id == AclResource.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    resources = [AclResourceRow(*row) for row in resource_rows]
    findings = detect_acl_resource_conflicts(resources)
    await _persist_conflict_findings(session, root, "acl_resource_conflict", findings)


async def _detect_and_persist_indexer_conflicts(session: AsyncSession, root: Path) -> None:
    indexer_rows = (
        await session.execute(
            select(ModuleIndexer.module_id, Module.name, ModuleIndexer.indexer_id)
            .join(Module, Module.id == ModuleIndexer.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    indexers = [IndexerRow(*row) for row in indexer_rows]
    findings = detect_indexer_conflicts(indexers)
    await _persist_conflict_findings(session, root, "indexer_id_conflict", findings)


async def _detect_and_persist_mview_conflicts(session: AsyncSession, root: Path) -> None:
    mview_rows = (
        await session.execute(
            select(ModuleMview.module_id, Module.name, ModuleMview.view_id)
            .join(Module, Module.id == ModuleMview.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    mviews = [MviewRow(*row) for row in mview_rows]
    findings = detect_mview_conflicts(mviews)
    await _persist_conflict_findings(session, root, "view_id_conflict", findings)


async def _fetch_route_rows(session: AsyncSession, root: Path) -> list[RouteRow]:
    route_rows = (
        await session.execute(
            select(
                ModuleRoute.module_id, Module.name, ModuleRoute.area, ModuleRoute.route_id, ModuleRoute.front_name
            )
            .join(Module, Module.id == ModuleRoute.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    return [RouteRow(*row) for row in route_rows]


async def _detect_and_persist_route_id_conflicts(session: AsyncSession, root: Path) -> None:
    routes = await _fetch_route_rows(session, root)
    findings = detect_route_id_conflicts(routes)
    await _persist_conflict_findings(session, root, "route_id_conflict", findings)


async def _detect_and_persist_frontname_conflicts(session: AsyncSession, root: Path) -> None:
    routes = await _fetch_route_rows(session, root)
    findings = detect_frontname_conflicts(routes)
    await _persist_conflict_findings(session, root, "frontname_conflict", findings)


async def _detect_and_persist_db_schema_conflicts(session: AsyncSession, root: Path) -> None:
    column_rows = (
        await session.execute(
            select(
                DbColumn.module_id,
                Module.name,
                DbColumn.table_name,
                DbColumn.column_name,
                DbColumn.xsi_type,
                DbColumn.nullable,
            )
            .join(Module, Module.id == DbColumn.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    columns = [DbColumnRow(*row) for row in column_rows]

    findings = detect_db_schema_conflicts(columns)
    await _persist_conflict_findings(session, root, "db_schema_conflict", findings)


async def _detect_and_persist_circular_dependencies(session: AsyncSession, root: Path) -> None:
    dependency_rows = (
        await session.execute(
            select(ModuleDependency.module_id, Module.name, ModuleDependency.depends_on_name)
            .join(Module, Module.id == ModuleDependency.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    deps = [ModuleDependencyRow(*row) for row in dependency_rows]

    findings = detect_circular_dependencies(deps)
    await _persist_conflict_findings(session, root, "circular_dependency", findings)


async def _detect_and_persist_preference_conflicts(session: AsyncSession, root: Path) -> None:
    preference_rows = (
        await session.execute(
            select(DiPreference.module_id, Module.name, DiPreference.for_type, DiPreference.preference_type)
            .join(Module, Module.id == DiPreference.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    preferences = [PreferenceRow(*row) for row in preference_rows]

    findings = detect_preference_conflicts(preferences)
    await _persist_conflict_findings(session, root, "preference_conflict", findings)


async def _detect_and_persist_virtual_type_conflicts(session: AsyncSession, root: Path) -> None:
    virtual_type_rows = (
        await session.execute(
            select(DiVirtualType.module_id, Module.name, DiVirtualType.name, DiVirtualType.virtual_type)
            .join(Module, Module.id == DiVirtualType.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    virtual_types = [VirtualTypeRow(*row) for row in virtual_type_rows]

    findings = detect_virtual_type_conflicts(virtual_types)
    await _persist_conflict_findings(session, root, "virtual_type_conflict", findings)


async def _detect_and_persist_widget_id_conflicts(session: AsyncSession, root: Path) -> None:
    widget_rows = (
        await session.execute(
            select(ModuleWidget.module_id, Module.name, ModuleWidget.widget_id)
            .join(Module, Module.id == ModuleWidget.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    widgets = [WidgetRow(*row) for row in widget_rows]

    findings = detect_widget_id_conflicts(widgets)
    await _persist_conflict_findings(session, root, "widget_id_conflict", findings)


async def _detect_and_persist_cron_job_conflicts(session: AsyncSession, root: Path) -> None:
    job_rows = (
        await session.execute(
            select(CronJob.module_id, Module.name, CronJob.job_name, CronJob.instance_class, CronJob.method)
            .join(Module, Module.id == CronJob.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    jobs = [CronJobRow(*row) for row in job_rows]

    findings = detect_cron_job_conflicts(jobs)
    await _persist_conflict_findings(session, root, "cron_job_conflict", findings)


async def _detect_and_persist_graphql_field_conflicts(session: AsyncSession, root: Path) -> None:
    field_rows = (
        await session.execute(
            select(
                GraphQlField.module_id,
                Module.name,
                GraphQlField.operation_type,
                GraphQlField.type_name,
                GraphQlField.field_name,
                GraphQlField.resolver_class,
            )
            .join(Module, Module.id == GraphQlField.module_id)
            .where(Module.repo_root == str(root))
        )
    ).all()
    fields = [GraphQlFieldRow(*row) for row in field_rows]

    findings = detect_graphql_field_conflicts(fields)
    await _persist_conflict_findings(session, root, "graphql_field_conflict", findings)


_ModuleChildModel = (
    type[DiPreference]
    | type[DiPlugin]
    | type[DiVirtualType]
    | type[EventObserver]
    | type[GraphQlField]
    | type[CronJob]
    | type[WebapiRoute]
    | type[ConfigField]
    | type[DbTable]
    | type[DbColumn]
    | type[QueueBinding]
    | type[AclResource]
    | type[ModuleIndexer]
    | type[ModuleMview]
    | type[ModuleRoute]
    | type[ModuleWidget]
)


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
        # DiPreference/DiPlugin/DiVirtualType/EventObserver/GraphQlField/CronJob are
        # deleted together with their reinsertion in _sync_module_children below,
        # not here.
        await session.execute(delete(FileHash).where(FileHash.module_id == module.id))
        if diff.is_empty():
            # Nothing about this module's own files changed, so the checks
            # purely derived from them (composer-completeness, deprecated-
            # annotation, hardcoded-secret, and PHP static analysis) can't have
            # changed either -- leave their existing rows alone rather than
            # paying for a real round-trip to php-analyzer per tool per module
            # for a result that's guaranteed identical. Checks that depend on
            # *external* data (security advisories, abandoned/outdated
            # dependencies, Magento release compatibility) are deleted and
            # recomputed below regardless, since that data can change even
            # when this module's own code hasn't.
            await session.execute(
                delete(ModuleQualityFinding).where(
                    ModuleQualityFinding.module_id == module.id,
                    ModuleQualityFinding.check_type.notin_(_FILE_HASH_DEPENDENT_CHECK_TYPES),
                )
            )
        else:
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
    module.homepage = pm.composer.homepage if pm.composer else None
    module.authors = pm.composer.authors if pm.composer else []
    module.php_extensions = pm.composer.php_extensions if pm.composer else []
    module.composer_scripts = pm.composer.scripts if pm.composer else []
    module.composer_autoload_psr4 = pm.composer.autoload_psr4 if pm.composer else {}
    module.composer_allow_plugins = pm.composer.allow_plugins if pm.composer else {}
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
    await _sync_module_children(session, module.id, DiVirtualType, pm.di.virtual_types)
    await _sync_module_children(session, module.id, EventObserver, pm.events)
    outcome.observers = len(pm.events)
    await _sync_module_children(session, module.id, GraphQlField, pm.graphql)
    await _sync_module_children(session, module.id, CronJob, pm.cron_jobs)
    await _sync_module_children(session, module.id, WebapiRoute, pm.webapi_routes)
    await _sync_module_children(session, module.id, ConfigField, pm.config_fields)
    await _sync_module_children(session, module.id, DbTable, pm.db_tables)
    await _sync_module_children(session, module.id, DbColumn, pm.db_columns)
    await _sync_module_children(session, module.id, QueueBinding, pm.queue_bindings)
    await _sync_module_children(session, module.id, AclResource, pm.acl_resources)
    await _sync_module_children(session, module.id, ModuleIndexer, pm.indexers)
    await _sync_module_children(session, module.id, ModuleMview, pm.mviews)
    await _sync_module_children(session, module.id, ModuleRoute, pm.routes)
    await _sync_module_children(session, module.id, ModuleWidget, pm.widgets)

    classes = catalog_module_classes(pm.discovered.root)
    outcome.classes = len(classes)
    # phpmetrics (check_php_static_analysis below) reports class FQCNs, not
    # file paths like every other PHP-toolchain tool — resolved against this
    # module's own catalog rather than a DB round-trip, so that check can
    # stay genuinely independent of `session` and run concurrently with the
    # other quality checks.
    fqcn_to_file = {entry.fqcn: entry.file_path for entry in classes}

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

    skip_file_hash_dependent_checks = existing is not None and diff.is_empty()
    if skip_file_hash_dependent_checks:
        session_findings = await _session_based_checks()
        quality_findings = [*session_findings]
    else:
        session_findings, php_static_findings, (phpunit_result, phpunit_findings) = await asyncio.gather(
            _session_based_checks(),
            check_php_static_analysis(
                pm.discovered.root, repo_root, pm.composer.php_constraint if pm.composer else None, fqcn_to_file
            ),
            check_php_unit_tests(pm.discovered.root, pm.composer.php_constraint if pm.composer else None),
        )
        # None/None/None (not 0/0/None) means "never executed" -- only
        # overwrite these when the check actually ran this time, same "leave
        # it alone when there's nothing new to say" principle as the
        # findings-preservation skip above. A module that loses its real
        # Test/Unit directory would keep showing its last real numbers until
        # a future check revisits this -- same accepted staleness as every
        # other file-hash-dependent check here.
        if phpunit_result.executed:
            module.phpunit_tests_run = phpunit_result.tests_run
            module.phpunit_tests_failed = phpunit_result.tests_failed
            module.phpunit_coverage_percent = phpunit_result.coverage_percent
        quality_findings = [
            *composer_completeness_findings(pm.composer),
            *check_license_risk(
                pm.composer.license if pm.composer else None, settings.license_risk_prefix_tuple
            ),
            *scan_deprecated_annotations(pm.discovered.root),
            *scan_hardcoded_secrets(pm.discovered.root),
            *find_missing_acl(classes),
            *session_findings,
            *php_static_findings,
            *phpunit_findings,
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
