from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DiPlugin,
    DiPreference,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
)


@dataclass
class OrphanedModule:
    module_id: int
    name: str
    composer_name: str | None
    path: str
    repo_root: str
    finding_counts: dict[str, int] = field(default_factory=dict)


async def find_orphaned_disabled_modules(session: AsyncSession, limit: int = 20) -> list[OrphanedModule]:
    """Disabled modules nothing else in the fleet still references -- no
    other module sequences after it (ModuleDependency), overrides one of its
    classes (DiPreference), or plugs into one of its classes (DiPlugin). The
    same three relation kinds GET /modules/{id}/graph's BFS
    (app/api/routes/modules.py's get_module_dependency_graph) already treats
    as "this module is referenced," just aggregated fleet-wide here instead
    of expanded from one center module.

    `enabled = False` is part of the definition, not just an extra filter --
    an orphaned-but-enabled module might still be reached directly (a
    storefront route, config.php, an admin menu entry) even with no other
    *module* pointing at it, so it isn't a deprecation candidate the same way
    a disabled-and-unreferenced one is.
    """
    has_dependency = (
        select(ModuleDependency.id)
        .where(ModuleDependency.depends_on_name == Module.name)
        .correlate(Module)
        .exists()
    )
    has_preference_override = (
        select(DiPreference.id)
        .join(PhpClass, PhpClass.fqcn == DiPreference.for_type)
        .where(PhpClass.module_id == Module.id)
        .correlate(Module)
        .exists()
    )
    has_plugin = (
        select(DiPlugin.id)
        .join(PhpClass, PhpClass.fqcn == DiPlugin.intercepted_type)
        .where(PhpClass.module_id == Module.id)
        .correlate(Module)
        .exists()
    )

    rows = (
        await session.execute(
            select(Module.id, Module.name, Module.composer_name, Module.path, Module.repo_root)
            .where(Module.enabled.is_(False), ~has_dependency, ~has_preference_override, ~has_plugin)
            .order_by(Module.name)
            .limit(limit)
        )
    ).all()

    module_ids = [row.id for row in rows]
    finding_counts_by_module: dict[int, dict[str, int]] = {}
    if module_ids:
        count_rows = (
            await session.execute(
                select(
                    ModuleQualityFinding.module_id, ModuleQualityFinding.check_type, func.count(ModuleQualityFinding.id)
                )
                .where(ModuleQualityFinding.module_id.in_(module_ids))
                .group_by(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type)
            )
        ).all()
        for module_id, check_type, count in count_rows:
            finding_counts_by_module.setdefault(module_id, {})[check_type] = count

    return [
        OrphanedModule(
            module_id=row.id,
            name=row.name,
            composer_name=row.composer_name,
            path=row.path,
            repo_root=row.repo_root,
            finding_counts=finding_counts_by_module.get(row.id, {}),
        )
        for row in rows
    ]
