import logging
import os
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.facts import gather_module_facts
from app.analyzer.readme import render_readme_markdown
from app.analyzer.schemas import ModuleDoc
from app.api.sse import format_sse
from app.config import settings
from app.db import get_session
from app.models import (
    ComposerPackageRequirement,
    ConfigField,
    CronJob,
    DbTable,
    DiPlugin,
    DiPreference,
    DiVirtualType,
    EventObserver,
    GraphQlField,
    Module,
    ModuleDependency,
    ModuleDocument,
    ModuleQualityFinding,
    PhpClass,
    PhpClassMethod,
    QueueBinding,
    WebapiRoute,
)
from app.sbom import SbomComponentInput, SbomRequirementInput, build_cyclonedx_sbom
from app.scanner.orchestrator import (
    ScanAlreadyInProgressError,
    ScanResult,
    scan_paths,
    scan_paths_events,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ScanRequest(BaseModel):
    path: str


class ModuleScanOutcomeResponse(BaseModel):
    name: str
    status: str
    state: str
    classes: int
    plugins: int
    observers: int
    files_added: int
    files_changed: int
    files_removed: int
    warnings: list[str]


class ScanResponse(BaseModel):
    repository: str
    duration_seconds: float
    modules_found: int
    modules_created: int
    modules_updated: int
    classes_total: int
    plugins_total: int
    observers_total: int
    tasks_enqueued: int
    warnings: list[str]
    modules: list[ModuleScanOutcomeResponse]
    stores_scanned: int


def _extract_tags(doc: dict | None) -> list[str]:
    if not doc:
        return []
    return [t.get("name") for t in doc.get("tags", []) if t.get("name")]


class ModuleSummary(BaseModel):
    id: int
    name: str
    composer_name: str | None
    source_type: str
    path: str
    repo_root: str
    enabled: bool | None
    state: str
    setup_version: str | None
    class_count: int
    plugin_count: int
    observer_count: int
    last_scanned_at: datetime
    tags: list[str] = []
    has_readme: bool = False
    has_tests: bool = False
    has_module_doc: bool = False
    # None means "never executed" (no real Test/Unit + own vendor/bin/
    # phpunit) -- see check_php_unit_tests.
    phpunit_tests_run: int | None = None
    phpunit_tests_failed: int | None = None
    phpunit_coverage_percent: float | None = None
    # check_type -> count, e.g. {"phpstan_error": 3, "hardcoded_secret": 1}. A
    # generic dict instead of one flat field per check_type (there were 12,
    # added incrementally across Phases 9/10/12 — CLAUDE.md's own Phase 12
    # note already flagged the flat-field shape as outgrowing "leave it
    # alone", confirmed by every one of those additions touching this model,
    # list_modules/list_repos's count-building code, and 3-4 frontend files
    # each). A new check_type now needs zero changes here.
    finding_counts: dict[str, int] = {}


class MethodSummary(BaseModel):
    name: str
    start_line: int | None
    end_line: int | None


class PhpClassSummary(BaseModel):
    fqcn: str
    kind: str
    file_path: str
    is_plugin: bool
    is_observer: bool
    role_signals: list[str]
    methods: list[MethodSummary]


class DiPreferenceSummary(BaseModel):
    for_type: str
    preference_type: str


class DiPluginSummary(BaseModel):
    intercepted_type: str
    plugin_name: str
    plugin_class: str
    sort_order: int | None
    disabled: bool


class DiVirtualTypeSummary(BaseModel):
    name: str
    virtual_type: str


class EventObserverSummary(BaseModel):
    event_name: str
    observer_name: str
    observer_class: str
    disabled: bool


class GraphQlFieldSummary(BaseModel):
    operation_type: str
    type_name: str
    field_name: str
    resolver_class: str | None


class CronJobSummary(BaseModel):
    job_name: str
    instance_class: str
    method: str
    schedule: str | None


class WebapiRouteSummary(BaseModel):
    url: str
    http_method: str
    service_class: str
    service_method: str
    acl_resource: str | None


class ConfigFieldSummary(BaseModel):
    section_id: str
    group_id: str
    field_id: str
    label: str | None
    field_type: str | None


class DbTableSummary(BaseModel):
    table_name: str
    comment: str | None
    column_count: int


class QueueBindingSummary(BaseModel):
    topic: str
    destination: str | None
    consumer_name: str | None
    handler_class: str | None
    handler_method: str | None


class QualityFindingResponse(BaseModel):
    check_type: str
    severity: str
    file_path: str | None
    line: int | None
    message: str


class ModuleDetail(ModuleSummary):
    license: list[str] | None = None
    homepage: str | None = None
    authors: list[str] = []
    php_extensions: list[str] = []
    composer_scripts: list[str] = []
    composer_autoload_psr4: dict[str, str] = {}
    composer_allow_plugins: dict[str, bool] = {}
    dependencies: list[str]
    classes: list[PhpClassSummary]
    preferences: list[DiPreferenceSummary]
    plugins: list[DiPluginSummary]
    virtual_types: list[DiVirtualTypeSummary] = []
    observers: list[EventObserverSummary]
    graphql_fields: list[GraphQlFieldSummary] = []
    cron_jobs: list[CronJobSummary] = []
    webapi_routes: list[WebapiRouteSummary] = []
    config_fields: list[ConfigFieldSummary] = []
    db_tables: list[DbTableSummary] = []
    queue_bindings: list[QueueBindingSummary] = []
    quality_findings: list[QualityFindingResponse] = []


class ScanRootsResponse(BaseModel):
    scan_roots: list[str]


@router.get("/scan-roots", response_model=ScanRootsResponse)
async def get_scan_roots() -> ScanRootsResponse:
    return ScanRootsResponse(scan_roots=settings.scan_roots)


def _not_a_directory_detail(path: str) -> str:
    hint = (
        f"must be under a configured scan root ({', '.join(settings.scan_roots)})"
        if settings.scan_roots
        else "no scan roots are configured — set MAGEWIKI_SCAN_ROOT_1 in .env and restart"
    )
    return f"not a directory: {path} — {hint}"


def _validate_scan_path(path: str) -> None:
    """The real access-control gate — settings.scan_roots was previously only used
    for the GET /scan-roots UI hint and this error text, never actually enforced, so
    any caller could scan arbitrary host paths the container could see. Both checks
    share one 400 response/message so a caller can't distinguish "not a directory"
    from "outside the allowed roots" and use that to probe the host filesystem.
    """
    if not settings.is_within_scan_roots(path) or not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=_not_a_directory_detail(path))


def _scan_response(result: ScanResult, duration_seconds: float) -> ScanResponse:
    return ScanResponse(
        repository=result.repo_root,
        duration_seconds=duration_seconds,
        modules_found=result.modules_found,
        modules_created=result.modules_created,
        modules_updated=result.modules_updated,
        classes_total=result.classes_total,
        plugins_total=result.plugins_total,
        observers_total=result.observers_total,
        tasks_enqueued=result.tasks_enqueued,
        warnings=result.warnings,
        modules=[
            ModuleScanOutcomeResponse(
                name=m.name, status=m.status, state=m.state, classes=m.classes, plugins=m.plugins,
                observers=m.observers, files_added=m.files_added, files_changed=m.files_changed,
                files_removed=m.files_removed, warnings=m.warnings,
            )
            for m in result.modules
        ],
        stores_scanned=result.stores_scanned,
    )


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest, session: AsyncSession = Depends(get_session)) -> ScanResponse:
    _validate_scan_path(request.path)

    started = time.monotonic()
    try:
        result = await scan_paths(request.path, session)
    except ScanAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    duration = time.monotonic() - started

    return _scan_response(result, duration)


async def _scan_sse_stream(path: str, session: AsyncSession) -> AsyncIterator[str]:
    started = time.monotonic()
    try:
        async for event in scan_paths_events(path, session):
            if event["event"] == "done":
                duration = time.monotonic() - started
                response = _scan_response(event["result"], duration)
                yield format_sse({"event": "done", "result": response.model_dump()})
            else:
                yield format_sse(event)
    except ScanAlreadyInProgressError as exc:
        yield format_sse({"event": "error", "detail": str(exc)})
    except Exception:
        # Whatever the whole-scan point of this SSE redesign was for — real
        # feedback instead of a silent hang — an uncaught exception here used to
        # defeat it just the same: the async generator simply stopped, the
        # StreamingResponse connection closed, and the UI stayed on "Scanning..."
        # forever with no indication anything failed. Log the real exception
        # server-side and still tell the client, rather than leaking internals.
        logger.exception("unexpected error during a streaming scan of %s", path)
        yield format_sse({"event": "error", "detail": "scan failed unexpectedly — check server logs"})


@router.post("/scan/stream")
async def scan_stream(request: ScanRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    """Live progress for a scan — same scan_paths_events() generator the
    non-streaming /scan drains silently, but piped straight to the client as
    SSE (same pattern as /chat) so the UI can show a progress bar and a
    terminal-style log instead of a single multi-minute blocking request with
    no feedback. Per-module commits in the generator mean GET /modules
    actually reflects progress mid-scan, not just at the end. `path` may be a
    single store root or a directory containing several stores side by side
    — scan_paths_events() expands and scans each one in turn, emitting a
    "store" event before each.
    """
    _validate_scan_path(request.path)
    return StreamingResponse(_scan_sse_stream(request.path, session), media_type="text/event-stream")


async def _quality_finding_counts_by_module(session: AsyncSession) -> dict[int, dict[str, int]]:
    """check_type counts grouped by module_id, for every module — shared by
    list_modules/list_repos, previously the exact same query copy-pasted in
    both.
    """
    rows = await session.execute(
        select(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type, func.count(ModuleQualityFinding.id))
        .group_by(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type)
    )
    counts_by_module: dict[int, dict[str, int]] = {}
    for module_id, check_type, count in rows:
        counts_by_module.setdefault(module_id, {})[check_type] = count
    return counts_by_module


@router.get("/modules", response_model=list[ModuleSummary])
async def list_modules(session: AsyncSession = Depends(get_session)) -> list[ModuleSummary]:
    class_count = (
        select(func.count(PhpClass.id))
        .where(PhpClass.module_id == Module.id)
        .correlate(Module)
        .scalar_subquery()
    )
    plugin_count = (
        select(func.count(PhpClass.id))
        .where(PhpClass.module_id == Module.id, PhpClass.is_plugin.is_(True))
        .correlate(Module)
        .scalar_subquery()
    )
    observer_count = (
        select(func.count(PhpClass.id))
        .where(PhpClass.module_id == Module.id, PhpClass.is_observer.is_(True))
        .correlate(Module)
        .scalar_subquery()
    )

    rows = await session.execute(
        select(Module, class_count, plugin_count, observer_count, ModuleDocument.doc)
        .outerjoin(ModuleDocument, ModuleDocument.module_id == Module.id)
        .order_by(Module.name)
    )
    module_rows = rows.all()
    counts_by_module = await _quality_finding_counts_by_module(session)

    summaries = []
    for row in module_rows:
        # SQLAlchemy's Select[] typing degenerates to `object` per element when
        # mixing an ORM entity with scalar_subquery()/joined columns like this —
        # confirmed via reveal_type, not stub incompleteness. cast() is the
        # type-level fix; zero runtime effect.
        module = cast(Module, row[0])
        classes = cast(int, row[1])
        plugins = cast(int, row[2])
        observers = cast(int, row[3])
        doc = cast(dict | None, row[4])
        summaries.append(
            ModuleSummary(
                id=module.id,
                name=module.name,
                composer_name=module.composer_name,
                source_type=module.source_type,
                path=module.path,
                repo_root=module.repo_root,
                enabled=module.enabled,
                state=module.state,
                setup_version=module.setup_version,
                class_count=classes,
                plugin_count=plugins,
                observer_count=observers,
                last_scanned_at=module.last_scanned_at,
                tags=_extract_tags(doc),
                has_readme=module.has_readme,
                has_tests=module.has_tests,
                has_module_doc=doc is not None,
                phpunit_tests_run=module.phpunit_tests_run,
                phpunit_tests_failed=module.phpunit_tests_failed,
                phpunit_coverage_percent=module.phpunit_coverage_percent,
                finding_counts=counts_by_module.get(module.id, {}),
            )
        )
    return summaries


class RepoSummary(BaseModel):
    """Phase 11: aggregate health across every repo MageWiki has scanned.
    `Module.repo_root` already lets multiple repos coexist in one DB — this
    is purely an aggregation over existing data, no multi-tenancy/"client"
    concept, per docs/v1-port-roadmap.md's scoped-down Phase 11 design.
    """

    repo_root: str
    module_count: int
    enabled_count: int
    has_readme_count: int
    has_tests_count: int
    finding_counts: dict[str, int] = {}
    last_scanned_at: datetime


@router.get("/repos", response_model=list[RepoSummary])
async def list_repos(session: AsyncSession = Depends(get_session)) -> list[RepoSummary]:
    module_rows = (
        await session.execute(
            select(
                Module.repo_root,
                Module.id,
                Module.enabled,
                Module.has_readme,
                Module.has_tests,
                Module.last_scanned_at,
            )
        )
    ).all()

    counts_by_module = await _quality_finding_counts_by_module(session)

    repos: dict[str, dict] = {}
    for repo_root, module_id, enabled, has_readme, has_tests, last_scanned_at in module_rows:
        repo = repos.setdefault(
            repo_root,
            {
                "module_count": 0,
                "enabled_count": 0,
                "has_readme_count": 0,
                "has_tests_count": 0,
                "finding_counts": {},
                "last_scanned_at": last_scanned_at,
            },
        )
        repo["module_count"] += 1
        if enabled:
            repo["enabled_count"] += 1
        if has_readme:
            repo["has_readme_count"] += 1
        if has_tests:
            repo["has_tests_count"] += 1
        for check_type, count in counts_by_module.get(module_id, {}).items():
            repo["finding_counts"][check_type] = repo["finding_counts"].get(check_type, 0) + count
        repo["last_scanned_at"] = max(repo["last_scanned_at"], last_scanned_at)

    return [RepoSummary(repo_root=repo_root, **data) for repo_root, data in sorted(repos.items())]


@router.get("/repos/sbom")
async def get_repo_sbom(repo_root: str, session: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A CycloneDX 1.5 JSON SBOM for every module currently scanned under one
    repo_root — one "library" component per module, built purely from data
    already parsed and persisted (composer name/version/license/homepage), no
    new scan or external call. Closes a real SCA gap: the existing CVE/
    abandoned-dependency checks already evaluate this same data, but nothing
    exported it in a standard, tool-consumable format a security team could
    feed into Dependency-Track or another SBOM consumer.

    Also includes a one-level dependency graph: each module's own direct,
    production composer requirements (already parsed into
    composer_package_requirements for the CVE/abandoned-dependency checks),
    as CycloneDX `dependencies` entries — see build_cyclonedx_sbom()'s own
    docstring for why this is "direct," not a fully-resolved transitive tree.
    """
    rows = (
        await session.execute(
            select(
                Module.id, Module.name, Module.composer_name, Module.setup_version, Module.license, Module.homepage
            ).where(Module.repo_root == repo_root)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="no modules scanned under this repo_root")

    bom_ref_by_module_id = {module_id: composer_name or name for module_id, name, composer_name, _, _, _ in rows}
    components = [
        SbomComponentInput(name=name, composer_name=composer_name, version=version, license=license_, homepage=homepage)
        for _, name, composer_name, version, license_, homepage in rows
    ]

    requirement_rows = (
        await session.execute(
            select(ComposerPackageRequirement.module_id, ComposerPackageRequirement.package_name).where(
                ComposerPackageRequirement.module_id.in_(bom_ref_by_module_id),
                ComposerPackageRequirement.is_dev.is_(False),
            )
        )
    ).all()
    requirements = [
        SbomRequirementInput(module_bom_ref=bom_ref_by_module_id[module_id], package_name=package_name)
        for module_id, package_name in requirement_rows
    ]

    sbom = build_cyclonedx_sbom(repo_root, components, requirements)

    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(repo_root).name) or "sbom"
    return JSONResponse(
        content=sbom,
        media_type="application/vnd.cyclonedx+json",
        headers={"Content-Disposition": f'attachment; filename="sbom-{safe_name}.json"'},
    )


class OverlapStoreEntry(BaseModel):
    repo_root: str
    current_hash: str | None
    setup_version: str | None
    enabled: bool | None


class ModuleOverlapEntry(BaseModel):
    name: str
    composer_name: str | None
    store_count: int
    version_drift: bool
    stores: list[OverlapStoreEntry]


@router.get("/modules/overlap", response_model=list[ModuleOverlapEntry])
async def list_module_overlap(session: AsyncSession = Depends(get_session)) -> list[ModuleOverlapEntry]:
    """Modules installed under more than one repo_root — e.g. a shared
    in-house module deployed to several stores, or the same third-party
    module repeated across a fleet. Module.current_hash is computed purely
    from path-relative-to-module-root + file bytes (repo_root never enters
    the hash), so two installs of the literally same version naturally hash
    identically — version_drift flags when they don't.
    """
    rows = (
        await session.execute(
            select(
                Module.name,
                Module.composer_name,
                Module.repo_root,
                Module.current_hash,
                Module.setup_version,
                Module.enabled,
            )
        )
    ).all()

    by_name: dict[str, list] = {}
    for name, composer_name, repo_root, current_hash, setup_version, enabled in rows:
        by_name.setdefault(name, []).append((composer_name, repo_root, current_hash, setup_version, enabled))

    entries = []
    for name, group in by_name.items():
        if len({repo_root for _, repo_root, _, _, _ in group}) < 2:
            continue
        composer_name = next((c for c, _, _, _, _ in group if c), None)
        hashes = {h for _, _, h, _, _ in group}
        entries.append(
            ModuleOverlapEntry(
                name=name,
                composer_name=composer_name,
                store_count=len(group),
                version_drift=len(hashes) > 1,
                stores=[
                    OverlapStoreEntry(
                        repo_root=repo_root, current_hash=current_hash, setup_version=setup_version, enabled=enabled
                    )
                    for _, repo_root, current_hash, setup_version, enabled in sorted(group, key=lambda g: g[1])
                ],
            )
        )

    entries.sort(key=lambda e: (-e.store_count, e.name))
    return entries


@router.get("/modules/{module_id}", response_model=ModuleDetail)
async def get_module(module_id: int, session: AsyncSession = Depends(get_session)) -> ModuleDetail:
    module = await session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")

    dependencies = (
        await session.scalars(select(ModuleDependency).where(ModuleDependency.module_id == module_id))
    ).all()
    classes = (
        await session.scalars(select(PhpClass).where(PhpClass.module_id == module_id))
    ).all()
    preferences = (
        await session.scalars(select(DiPreference).where(DiPreference.module_id == module_id))
    ).all()
    plugins = (
        await session.scalars(select(DiPlugin).where(DiPlugin.module_id == module_id))
    ).all()
    virtual_types = (
        await session.scalars(select(DiVirtualType).where(DiVirtualType.module_id == module_id))
    ).all()
    observers = (
        await session.scalars(select(EventObserver).where(EventObserver.module_id == module_id))
    ).all()
    graphql_fields = (
        await session.scalars(select(GraphQlField).where(GraphQlField.module_id == module_id))
    ).all()
    cron_jobs = (await session.scalars(select(CronJob).where(CronJob.module_id == module_id))).all()
    webapi_routes = (
        await session.scalars(select(WebapiRoute).where(WebapiRoute.module_id == module_id))
    ).all()
    config_fields = (
        await session.scalars(select(ConfigField).where(ConfigField.module_id == module_id))
    ).all()
    db_tables = (await session.scalars(select(DbTable).where(DbTable.module_id == module_id))).all()
    queue_bindings = (
        await session.scalars(select(QueueBinding).where(QueueBinding.module_id == module_id))
    ).all()
    quality_findings = (
        await session.scalars(select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module_id))
    ).all()
    doc_row = await session.scalar(select(ModuleDocument.doc).where(ModuleDocument.module_id == module_id))

    all_methods = (
        await session.scalars(
            select(PhpClassMethod).where(PhpClassMethod.class_id.in_([c.id for c in classes]))
        )
    ).all()
    methods_by_class_id: dict[int, list[PhpClassMethod]] = {}
    for m in all_methods:
        methods_by_class_id.setdefault(m.class_id, []).append(m)

    class_summaries = []
    for c in classes:
        methods = methods_by_class_id.get(c.id, [])
        class_summaries.append(
            PhpClassSummary(
                fqcn=c.fqcn, kind=c.kind, file_path=c.file_path, is_plugin=c.is_plugin,
                is_observer=c.is_observer, role_signals=c.role_signals,
                methods=[MethodSummary(name=m.name, start_line=m.start_line, end_line=m.end_line) for m in methods],
            )
        )

    return ModuleDetail(
        id=module.id,
        name=module.name,
        composer_name=module.composer_name,
        source_type=module.source_type,
        path=module.path,
        repo_root=module.repo_root,
        enabled=module.enabled,
        state=module.state,
        setup_version=module.setup_version,
        license=module.license,
        homepage=module.homepage,
        authors=module.authors or [],
        php_extensions=module.php_extensions or [],
        composer_scripts=module.composer_scripts or [],
        composer_autoload_psr4=module.composer_autoload_psr4 or {},
        composer_allow_plugins=module.composer_allow_plugins or {},
        class_count=len(classes),
        plugin_count=sum(1 for c in classes if c.is_plugin),
        observer_count=sum(1 for c in classes if c.is_observer),
        last_scanned_at=module.last_scanned_at,
        tags=_extract_tags(doc_row),
        has_readme=module.has_readme,
        has_tests=module.has_tests,
        has_module_doc=doc_row is not None,
        phpunit_tests_run=module.phpunit_tests_run,
        phpunit_tests_failed=module.phpunit_tests_failed,
        phpunit_coverage_percent=module.phpunit_coverage_percent,
        finding_counts=dict(Counter(f.check_type for f in quality_findings)),
        dependencies=[d.depends_on_name for d in dependencies],
        classes=class_summaries,
        # Each Summary's field names already match its ORM row's attributes exactly
        # (confirmed for all four) — model_validate(..., from_attributes=True) stays
        # correct automatically as fields are added, instead of a hand-written
        # field-by-field constructor call per entity type (4 near-identical copies
        # before this).
        preferences=[DiPreferenceSummary.model_validate(p, from_attributes=True) for p in preferences],
        plugins=[DiPluginSummary.model_validate(p, from_attributes=True) for p in plugins],
        virtual_types=[DiVirtualTypeSummary.model_validate(vt, from_attributes=True) for vt in virtual_types],
        observers=[EventObserverSummary.model_validate(o, from_attributes=True) for o in observers],
        graphql_fields=[GraphQlFieldSummary.model_validate(gf, from_attributes=True) for gf in graphql_fields],
        cron_jobs=[CronJobSummary.model_validate(cj, from_attributes=True) for cj in cron_jobs],
        webapi_routes=[WebapiRouteSummary.model_validate(wr, from_attributes=True) for wr in webapi_routes],
        config_fields=[ConfigFieldSummary.model_validate(cf, from_attributes=True) for cf in config_fields],
        db_tables=[DbTableSummary.model_validate(t, from_attributes=True) for t in db_tables],
        queue_bindings=[QueueBindingSummary.model_validate(qb, from_attributes=True) for qb in queue_bindings],
        quality_findings=[
            QualityFindingResponse(
                check_type=f.check_type, severity=f.severity, file_path=f.file_path, line=f.line, message=f.message
            )
            for f in quality_findings
        ],
    )


@router.get("/modules/{module_id}/readme", response_class=PlainTextResponse)
async def get_module_readme(module_id: int, session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    module = await session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")

    doc_row = await session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module_id))
    if doc_row is None:
        raise HTTPException(status_code=404, detail="module has not been analyzed yet")

    doc = ModuleDoc.model_validate(doc_row.doc)
    facts = await gather_module_facts(session, module_id)

    markdown = render_readme_markdown(
        module_name=module.name,
        doc=doc,
        facts=facts,
        model=doc_row.model,
        prompt_version=doc_row.prompt_version,
        content_hash=doc_row.content_hash,
        updated_at=doc_row.updated_at,
    )
    return PlainTextResponse(content=markdown, media_type="text/markdown")


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str
    module_id: int | None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str


class DependencyGraphResponse(BaseModel):
    center_module_id: int
    center_label: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _module_node_id(module_id: int) -> str:
    return f"module:{module_id}"


def _external_node_id(name: str) -> str:
    return f"ext:{name}"


@router.get("/modules/{module_id}/graph", response_model=DependencyGraphResponse)
async def get_module_dependency_graph(
    module_id: int, session: AsyncSession = Depends(get_session)
) -> DependencyGraphResponse:
    """One-hop dependency graph centered on a module: depends_on/overrides/plugins
    in both directions. for_type/intercepted_type are bare FQCN strings, not
    foreign keys — resolving which module owns one requires a PhpClass lookup;
    an unresolved FQCN (core class not yet scanned) becomes an "external" node
    rather than a guess. See CLAUDE.md anti-hallucination rules.
    """
    center = await session.get(Module, module_id)
    if center is None:
        raise HTTPException(status_code=404, detail="module not found")

    center_id = _module_node_id(module_id)
    nodes: dict[str, GraphNode] = {
        center_id: GraphNode(id=center_id, label=center.name, kind="module", module_id=module_id)
    }
    edges: list[GraphEdge] = []

    def add_module_node(m: Module) -> str:
        node_id = _module_node_id(m.id)
        if node_id not in nodes:
            nodes[node_id] = GraphNode(id=node_id, label=m.name, kind="module", module_id=m.id)
        return node_id

    def add_external_node(name: str) -> str:
        node_id = _external_node_id(name)
        if node_id not in nodes:
            nodes[node_id] = GraphNode(id=node_id, label=name, kind="external", module_id=None)
        return node_id

    def add_edge(source: str, target: str, relation: str) -> None:
        if source != target:
            edges.append(GraphEdge(source=source, target=target, relation=relation))

    own_fqcns = (await session.scalars(select(PhpClass.fqcn).where(PhpClass.module_id == module_id))).all()

    dependencies = (
        await session.scalars(select(ModuleDependency).where(ModuleDependency.module_id == module_id))
    ).all()
    # Batched instead of one SELECT per dependency — a module with many
    # composer requirements otherwise issues one query per row here.
    dependency_names = [dep.depends_on_name for dep in dependencies]
    modules_by_name = {
        m.name: m
        for m in (await session.scalars(select(Module).where(Module.name.in_(dependency_names)))).all()
    }
    for dep in dependencies:
        target_module = modules_by_name.get(dep.depends_on_name)
        target_id = add_module_node(target_module) if target_module else add_external_node(dep.depends_on_name)
        add_edge(center_id, target_id, "depends_on")

    reverse_dependencies = (
        await session.execute(
            select(Module)
            .join(ModuleDependency, ModuleDependency.module_id == Module.id)
            .where(ModuleDependency.depends_on_name == center.name)
        )
    ).scalars().all()
    for source_module in reverse_dependencies:
        add_edge(add_module_node(source_module), center_id, "depends_on")

    preferences = (await session.scalars(select(DiPreference).where(DiPreference.module_id == module_id))).all()
    # Batched instead of one SELECT per preference.
    pref_owner_by_fqcn = {
        fqcn: owner
        for owner, fqcn in (
            await session.execute(
                select(Module, PhpClass.fqcn)
                .join(PhpClass, PhpClass.module_id == Module.id)
                .where(PhpClass.fqcn.in_([pref.for_type for pref in preferences]))
            )
        ).all()
    }
    for pref in preferences:
        owner = pref_owner_by_fqcn.get(pref.for_type)
        target_id = add_module_node(owner) if owner else add_external_node(pref.for_type)
        add_edge(center_id, target_id, "overrides")

    if own_fqcns:
        reverse_preferences = (
            await session.execute(
                select(Module)
                .join(DiPreference, DiPreference.module_id == Module.id)
                .where(DiPreference.for_type.in_(own_fqcns))
            )
        ).scalars().all()
        for source_module in reverse_preferences:
            add_edge(add_module_node(source_module), center_id, "overrides")

    plugins = (await session.scalars(select(DiPlugin).where(DiPlugin.module_id == module_id))).all()
    # Batched instead of one SELECT per plugin.
    plugin_owner_by_fqcn = {
        fqcn: owner
        for owner, fqcn in (
            await session.execute(
                select(Module, PhpClass.fqcn)
                .join(PhpClass, PhpClass.module_id == Module.id)
                .where(PhpClass.fqcn.in_([plugin.intercepted_type for plugin in plugins]))
            )
        ).all()
    }
    for plugin in plugins:
        owner = plugin_owner_by_fqcn.get(plugin.intercepted_type)
        target_id = add_module_node(owner) if owner else add_external_node(plugin.intercepted_type)
        add_edge(center_id, target_id, "plugins")

    if own_fqcns:
        reverse_plugins = (
            await session.execute(
                select(Module)
                .join(DiPlugin, DiPlugin.module_id == Module.id)
                .where(DiPlugin.intercepted_type.in_(own_fqcns))
            )
        ).scalars().all()
        for source_module in reverse_plugins:
            add_edge(add_module_node(source_module), center_id, "plugins")

    return DependencyGraphResponse(
        center_module_id=module_id,
        center_label=center.name,
        nodes=list(nodes.values()),
        edges=edges,
    )
