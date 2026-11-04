from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiPlugin, DiPreference, EventObserver, Module, ModuleDependency, PhpClass, PhpClassMethod
from app.scanner.composer_json import parse_composer_json
from app.scanner.config_php import parse_config_php
from app.scanner.di_xml import parse_di_xml
from app.scanner.discovery import find_modules
from app.scanner.dto import DiscoveredModule
from app.scanner.events_xml import parse_events_xml
from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml
from app.scanner.php_classes import catalog_module_classes


@dataclass
class ModuleScanOutcome:
    name: str
    status: str  # "created" | "updated" | "error"
    classes: int = 0
    plugins: int = 0
    observers: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    repo_root: str
    modules_found: int = 0
    modules_created: int = 0
    modules_updated: int = 0
    classes_total: int = 0
    plugins_total: int = 0
    observers_total: int = 0
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

    # Phase B: catalog PHP classes and persist each module in its own savepoint.
    for pm in parsed:
        outcome = ModuleScanOutcome(name=pm.module_xml.name, status="updated")
        try:
            async with session.begin_nested():
                await _persist_module(
                    session, root, pm, config_map, all_plugin_classes, all_observer_classes, outcome
                )
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

    await session.commit()
    return result


async def _persist_module(
    session: AsyncSession,
    repo_root: Path,
    pm: _ParsedModule,
    config_map: dict[str, bool] | None,
    all_plugin_classes: set[str],
    all_observer_classes: set[str],
    outcome: ModuleScanOutcome,
) -> None:
    name = pm.module_xml.name
    existing = await session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == name)
    )

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

    module.setup_version = pm.module_xml.setup_version
    module.composer_name = pm.composer.name if pm.composer else None
    module.composer_type = pm.composer.type if pm.composer else None
    module.license = pm.composer.license if pm.composer else None
    module.enabled = enabled
    module.last_scanned_at = now
    module.scan_warnings = list(outcome.warnings)

    await session.flush()  # assign module.id for new rows

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
