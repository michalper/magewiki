from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnalysisCache,
    DiPlugin,
    DiPreference,
    EventObserver,
    FileAnalysis,
    Module,
    ModuleDependency,
    PhpClass,
    PhpClassMethod,
)


@dataclass
class PhpClassFact:
    fqcn: str
    class_name: str
    kind: str
    file_path: str
    is_plugin: bool
    is_observer: bool
    extends: list[str]
    implements: list[str]
    methods: list[str]


@dataclass
class FileAnalysisFact:
    relative_path: str
    file_summary: str
    notable_behavior: str | None


@dataclass
class ModuleFacts:
    name: str
    composer_name: str | None
    composer_type: str | None
    license: list[str] | None
    enabled: bool | None
    setup_version: str | None
    dependencies: list[str] = field(default_factory=list)
    php_classes: list[PhpClassFact] = field(default_factory=list)
    di_preferences: list[tuple[str, str]] = field(default_factory=list)
    di_plugins: list[tuple[str, str, str]] = field(default_factory=list)  # intercepted_type, plugin_name, plugin_class
    event_observers: list[tuple[str, str, str]] = field(default_factory=list)  # event, observer_name, observer_class
    file_analyses: list[FileAnalysisFact] = field(default_factory=list)


async def gather_module_facts(session: AsyncSession, module_id: int) -> ModuleFacts:
    module = await session.get(Module, module_id)
    if module is None:
        raise ValueError(f"no module with id {module_id}")

    dependencies = (
        await session.scalars(select(ModuleDependency).where(ModuleDependency.module_id == module_id))
    ).all()

    php_classes = (await session.scalars(select(PhpClass).where(PhpClass.module_id == module_id))).all()
    php_class_facts = []
    for c in php_classes:
        methods = (
            await session.scalars(select(PhpClassMethod).where(PhpClassMethod.class_id == c.id))
        ).all()
        php_class_facts.append(
            PhpClassFact(
                fqcn=c.fqcn,
                class_name=c.class_name,
                kind=c.kind,
                file_path=c.file_path,
                is_plugin=c.is_plugin,
                is_observer=c.is_observer,
                extends=c.extends or [],
                implements=c.implements or [],
                methods=[m.name for m in methods],
            )
        )

    preferences = (
        await session.scalars(select(DiPreference).where(DiPreference.module_id == module_id))
    ).all()
    plugins = (await session.scalars(select(DiPlugin).where(DiPlugin.module_id == module_id))).all()
    observers = (
        await session.scalars(select(EventObserver).where(EventObserver.module_id == module_id))
    ).all()

    file_analysis_rows = (
        await session.execute(
            select(FileAnalysis, AnalysisCache)
            .join(AnalysisCache, FileAnalysis.cache_id == AnalysisCache.id)
            .where(FileAnalysis.module_id == module_id)
        )
    ).all()
    file_analyses = [
        FileAnalysisFact(
            relative_path=fa.relative_path,
            file_summary=cache.response.get("file_summary", ""),
            notable_behavior=cache.response.get("notable_behavior"),
        )
        for fa, cache in file_analysis_rows
    ]

    return ModuleFacts(
        name=module.name,
        composer_name=module.composer_name,
        composer_type=module.composer_type,
        license=module.license,
        enabled=module.enabled,
        setup_version=module.setup_version,
        dependencies=[d.depends_on_name for d in dependencies],
        php_classes=php_class_facts,
        di_preferences=[(p.for_type, p.preference_type) for p in preferences],
        di_plugins=[(p.intercepted_type, p.plugin_name, p.plugin_class) for p in plugins],
        event_observers=[(o.event_name, o.observer_name, o.observer_class) for o in observers],
        file_analyses=file_analyses,
    )


def known_sources(facts: ModuleFacts) -> set[str]:
    sources = {fa.relative_path for fa in facts.file_analyses}
    sources.update(c.fqcn for c in facts.php_classes)
    sources.update(c.file_path for c in facts.php_classes)
    return sources
