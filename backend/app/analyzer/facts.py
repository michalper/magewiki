from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnalysisCache,
    ConfigField,
    CronJob,
    DbTable,
    DiPlugin,
    DiPreference,
    DiVirtualType,
    EventObserver,
    FileAnalysis,
    GraphQlField,
    Module,
    ModuleDependency,
    PhpClass,
    PhpClassMethod,
    QueueBinding,
    WebapiRoute,
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
    di_virtual_types: list[tuple[str, str]] = field(default_factory=list)  # name, virtual_type
    event_observers: list[tuple[str, str, str]] = field(default_factory=list)  # event, observer_name, observer_class
    # operation_type, type_name, field_name, resolver_class
    graphql_fields: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    cron_jobs: list[tuple[str, str, str, str | None]] = field(default_factory=list)  # name, class, method, schedule
    # url, http_method, service_class, service_method, acl_resource
    webapi_routes: list[tuple[str, str, str, str, str | None]] = field(default_factory=list)
    config_fields: list[tuple[str, str | None]] = field(default_factory=list)  # path, label
    db_tables: list[tuple[str, str | None, int]] = field(default_factory=list)  # name, comment, column_count
    # topic, destination, consumer_name, handler_class, handler_method
    queue_bindings: list[tuple[str, str | None, str | None, str | None, str | None]] = field(default_factory=list)
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
        di_virtual_types=[(vt.name, vt.virtual_type) for vt in virtual_types],
        event_observers=[(o.event_name, o.observer_name, o.observer_class) for o in observers],
        graphql_fields=[
            (gf.operation_type, gf.type_name, gf.field_name, gf.resolver_class) for gf in graphql_fields
        ],
        cron_jobs=[(cj.job_name, cj.instance_class, cj.method, cj.schedule) for cj in cron_jobs],
        webapi_routes=[
            (wr.url, wr.http_method, wr.service_class, wr.service_method, wr.acl_resource)
            for wr in webapi_routes
        ],
        config_fields=[(f"{cf.section_id}/{cf.group_id}/{cf.field_id}", cf.label) for cf in config_fields],
        db_tables=[(t.table_name, t.comment, t.column_count) for t in db_tables],
        queue_bindings=[
            (qb.topic, qb.destination, qb.consumer_name, qb.handler_class, qb.handler_method)
            for qb in queue_bindings
        ],
        file_analyses=file_analyses,
    )


def known_sources(facts: ModuleFacts) -> set[str]:
    sources = {fa.relative_path for fa in facts.file_analyses}
    sources.update(c.fqcn for c in facts.php_classes)
    sources.update(c.file_path for c in facts.php_classes)
    return sources


def known_config_paths(facts: ModuleFacts) -> set[str]:
    return {path for path, _label in facts.config_fields}
