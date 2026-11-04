import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import DiPlugin, DiPreference, EventObserver, Module, ModuleDependency, PhpClass, PhpClassMethod
from app.scanner.orchestrator import scan_repository

router = APIRouter()


class ScanRequest(BaseModel):
    path: str


class ModuleScanOutcomeResponse(BaseModel):
    name: str
    status: str
    classes: int
    plugins: int
    observers: int
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
    warnings: list[str]
    modules: list[ModuleScanOutcomeResponse]


class ModuleSummary(BaseModel):
    id: int
    name: str
    composer_name: str | None
    source_type: str
    path: str
    enabled: bool | None
    class_count: int
    plugin_count: int
    observer_count: int
    last_scanned_at: datetime


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


class ModuleDetail(ModuleSummary):
    dependencies: list[str]
    classes: list[PhpClassSummary]
    preferences: list[DiPreferenceSummary]
    plugins: list[DiPluginSummary]
    observers: list[EventObserverSummary]


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest, session: AsyncSession = Depends(get_session)) -> ScanResponse:
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail=f"not a directory: {request.path}")

    started = time.monotonic()
    result = await scan_repository(request.path, session)
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
        warnings=result.warnings,
        modules=[
            ModuleScanOutcomeResponse(
                name=m.name, status=m.status, classes=m.classes, plugins=m.plugins,
                observers=m.observers, warnings=m.warnings,
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
        select(Module, class_count, plugin_count, observer_count).order_by(Module.name)
    )

    return [
        ModuleSummary(
            id=module.id,
            name=module.name,
            composer_name=module.composer_name,
            source_type=module.source_type,
            path=module.path,
            enabled=module.enabled,
            class_count=classes,
            plugin_count=plugins,
            observer_count=observers,
            last_scanned_at=module.last_scanned_at,
        )
        for module, classes, plugins, observers in rows
    ]


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
        enabled=module.enabled,
        class_count=len(classes),
        plugin_count=sum(1 for c in classes if c.is_plugin),
        observer_count=sum(1 for c in classes if c.is_observer),
        last_scanned_at=module.last_scanned_at,
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
    )
