import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.facts import gather_module_facts
from app.analyzer.readme import render_readme_markdown
from app.analyzer.schemas import ModuleDoc
from app.db import get_session
from app.models import (
    DiPlugin,
    DiPreference,
    EventObserver,
    Module,
    ModuleDependency,
    ModuleDocument,
    ModuleQualityFinding,
    PhpClass,
    PhpClassMethod,
)
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository

router = APIRouter()


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
    class_count: int
    plugin_count: int
    observer_count: int
    last_scanned_at: datetime
    tags: list[str] = []
    has_readme: bool = False
    has_tests: bool = False
    has_module_doc: bool = False
    composer_issue_count: int = 0
    deprecated_count: int = 0
    secrets_count: int = 0
    security_advisory_count: int = 0
    abandoned_dependency_count: int = 0
    outdated_dependency_count: int = 0
    phpstan_error_count: int = 0
    phpmd_issue_count: int = 0
    phpcs_violation_count: int = 0
    php_compat_issue_count: int = 0
    magento_php_incompatible_count: int = 0
    magento_version_blocker_count: int = 0


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


class EventObserverSummary(BaseModel):
    event_name: str
    observer_name: str
    observer_class: str
    disabled: bool


class QualityFindingResponse(BaseModel):
    check_type: str
    severity: str
    file_path: str | None
    line: int | None
    message: str


class ModuleDetail(ModuleSummary):
    dependencies: list[str]
    classes: list[PhpClassSummary]
    preferences: list[DiPreferenceSummary]
    plugins: list[DiPluginSummary]
    observers: list[EventObserverSummary]
    quality_findings: list[QualityFindingResponse] = []


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest, session: AsyncSession = Depends(get_session)) -> ScanResponse:
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail=f"not a directory: {request.path}")

    started = time.monotonic()
    try:
        result = await scan_repository(request.path, session)
    except ScanAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    duration = time.monotonic() - started

    return ScanResponse(
        repository=result.repo_root,
        duration_seconds=duration,
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
    )


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

    finding_count_rows = await session.execute(
        select(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type, func.count(ModuleQualityFinding.id))
        .group_by(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type)
    )
    counts_by_module: dict[int, dict[str, int]] = {}
    for module_id, check_type, count in finding_count_rows:
        counts_by_module.setdefault(module_id, {})[check_type] = count

    return [
        ModuleSummary(
            id=module.id,
            name=module.name,
            composer_name=module.composer_name,
            source_type=module.source_type,
            path=module.path,
            repo_root=module.repo_root,
            enabled=module.enabled,
            state=module.state,
            class_count=classes,
            plugin_count=plugins,
            observer_count=observers,
            last_scanned_at=module.last_scanned_at,
            tags=_extract_tags(doc),
            has_readme=module.has_readme,
            has_tests=module.has_tests,
            has_module_doc=doc is not None,
            composer_issue_count=counts_by_module.get(module.id, {}).get("composer_completeness", 0),
            deprecated_count=counts_by_module.get(module.id, {}).get("deprecated_annotation", 0),
            secrets_count=counts_by_module.get(module.id, {}).get("hardcoded_secret", 0),
            security_advisory_count=counts_by_module.get(module.id, {}).get("security_advisory", 0),
            abandoned_dependency_count=counts_by_module.get(module.id, {}).get("abandoned_dependency", 0),
            outdated_dependency_count=counts_by_module.get(module.id, {}).get("outdated_dependency", 0),
            phpstan_error_count=counts_by_module.get(module.id, {}).get("phpstan_error", 0),
            phpmd_issue_count=counts_by_module.get(module.id, {}).get("phpmd_issue", 0),
            phpcs_violation_count=counts_by_module.get(module.id, {}).get("phpcs_violation", 0),
            php_compat_issue_count=counts_by_module.get(module.id, {}).get("php_compat_issue", 0),
            magento_php_incompatible_count=counts_by_module.get(module.id, {}).get(
                "magento_php_incompatible", 0
            ),
            magento_version_blocker_count=counts_by_module.get(module.id, {}).get(
                "magento_version_blocker", 0
            ),
        )
        for module, classes, plugins, observers, doc in module_rows
    ]


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
    composer_issue_count: int
    deprecated_count: int
    secrets_count: int
    security_advisory_count: int
    abandoned_dependency_count: int
    outdated_dependency_count: int
    phpstan_error_count: int
    phpmd_issue_count: int
    phpcs_violation_count: int
    php_compat_issue_count: int
    magento_php_incompatible_count: int
    magento_version_blocker_count: int
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

    finding_count_rows = await session.execute(
        select(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type, func.count(ModuleQualityFinding.id))
        .group_by(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type)
    )
    counts_by_module: dict[int, dict[str, int]] = {}
    for module_id, check_type, count in finding_count_rows:
        counts_by_module.setdefault(module_id, {})[check_type] = count

    repos: dict[str, dict] = {}
    for repo_root, module_id, enabled, has_readme, has_tests, last_scanned_at in module_rows:
        repo = repos.setdefault(
            repo_root,
            {
                "module_count": 0,
                "enabled_count": 0,
                "has_readme_count": 0,
                "has_tests_count": 0,
                "composer_issue_count": 0,
                "deprecated_count": 0,
                "secrets_count": 0,
                "security_advisory_count": 0,
                "abandoned_dependency_count": 0,
                "outdated_dependency_count": 0,
                "phpstan_error_count": 0,
                "phpmd_issue_count": 0,
                "phpcs_violation_count": 0,
                "php_compat_issue_count": 0,
                "magento_php_incompatible_count": 0,
                "magento_version_blocker_count": 0,
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
        counts = counts_by_module.get(module_id, {})
        repo["composer_issue_count"] += counts.get("composer_completeness", 0)
        repo["deprecated_count"] += counts.get("deprecated_annotation", 0)
        repo["secrets_count"] += counts.get("hardcoded_secret", 0)
        repo["security_advisory_count"] += counts.get("security_advisory", 0)
        repo["abandoned_dependency_count"] += counts.get("abandoned_dependency", 0)
        repo["outdated_dependency_count"] += counts.get("outdated_dependency", 0)
        repo["phpstan_error_count"] += counts.get("phpstan_error", 0)
        repo["phpmd_issue_count"] += counts.get("phpmd_issue", 0)
        repo["phpcs_violation_count"] += counts.get("phpcs_violation", 0)
        repo["php_compat_issue_count"] += counts.get("php_compat_issue", 0)
        repo["magento_php_incompatible_count"] += counts.get("magento_php_incompatible", 0)
        repo["magento_version_blocker_count"] += counts.get("magento_version_blocker", 0)
        if last_scanned_at > repo["last_scanned_at"]:
            repo["last_scanned_at"] = last_scanned_at

    return [RepoSummary(repo_root=repo_root, **data) for repo_root, data in sorted(repos.items())]


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
    observers = (
        await session.scalars(select(EventObserver).where(EventObserver.module_id == module_id))
    ).all()
    quality_findings = (
        await session.scalars(select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module_id))
    ).all()
    doc_row = await session.scalar(select(ModuleDocument.doc).where(ModuleDocument.module_id == module_id))

    class_summaries = []
    for c in classes:
        methods = (
            await session.scalars(select(PhpClassMethod).where(PhpClassMethod.class_id == c.id))
        ).all()
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
        class_count=len(classes),
        plugin_count=sum(1 for c in classes if c.is_plugin),
        observer_count=sum(1 for c in classes if c.is_observer),
        last_scanned_at=module.last_scanned_at,
        tags=_extract_tags(doc_row),
        has_readme=module.has_readme,
        has_tests=module.has_tests,
        has_module_doc=doc_row is not None,
        composer_issue_count=sum(1 for f in quality_findings if f.check_type == "composer_completeness"),
        deprecated_count=sum(1 for f in quality_findings if f.check_type == "deprecated_annotation"),
        secrets_count=sum(1 for f in quality_findings if f.check_type == "hardcoded_secret"),
        security_advisory_count=sum(1 for f in quality_findings if f.check_type == "security_advisory"),
        abandoned_dependency_count=sum(1 for f in quality_findings if f.check_type == "abandoned_dependency"),
        outdated_dependency_count=sum(1 for f in quality_findings if f.check_type == "outdated_dependency"),
        phpstan_error_count=sum(1 for f in quality_findings if f.check_type == "phpstan_error"),
        phpmd_issue_count=sum(1 for f in quality_findings if f.check_type == "phpmd_issue"),
        phpcs_violation_count=sum(1 for f in quality_findings if f.check_type == "phpcs_violation"),
        php_compat_issue_count=sum(1 for f in quality_findings if f.check_type == "php_compat_issue"),
        magento_php_incompatible_count=sum(
            1 for f in quality_findings if f.check_type == "magento_php_incompatible"
        ),
        magento_version_blocker_count=sum(
            1 for f in quality_findings if f.check_type == "magento_version_blocker"
        ),
        dependencies=[d.depends_on_name for d in dependencies],
        classes=class_summaries,
        preferences=[DiPreferenceSummary(for_type=p.for_type, preference_type=p.preference_type) for p in preferences],
        plugins=[
            DiPluginSummary(
                intercepted_type=p.intercepted_type, plugin_name=p.plugin_name, plugin_class=p.plugin_class,
                sort_order=p.sort_order, disabled=p.disabled,
            )
            for p in plugins
        ],
        observers=[
            EventObserverSummary(
                event_name=o.event_name, observer_name=o.observer_name, observer_class=o.observer_class,
                disabled=o.disabled,
            )
            for o in observers
        ],
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
    for dep in dependencies:
        target_module = await session.scalar(select(Module).where(Module.name == dep.depends_on_name))
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
    for pref in preferences:
        owner = (
            await session.execute(
                select(Module).join(PhpClass, PhpClass.module_id == Module.id).where(PhpClass.fqcn == pref.for_type)
            )
        ).scalars().first()
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
    for plugin in plugins:
        owner = (
            await session.execute(
                select(Module)
                .join(PhpClass, PhpClass.module_id == Module.id)
                .where(PhpClass.fqcn == plugin.intercepted_type)
            )
        ).scalars().first()
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
