from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiPlugin, DiPreference, Module, ModuleDependency, PhpClass

# Same safety-cap spirit as get_module_dependency_graph's own _MAX_GRAPH_NODES
# (app/api/routes/modules.py) -- a highly-connected core module could
# otherwise balloon a deep BFS into thousands of rows and as many round trips.
_MAX_IMPACT_MODULES = 200


@dataclass
class RemovalImpactEntry:
    module_id: int
    module_name: str
    hop: int  # 1 = depends directly on the removed module, 2+ = transitive
    relation: str  # "depends_on" | "overrides" | "plugins" -- the relation that first found it


@dataclass
class RemovalImpact:
    entries: list[RemovalImpactEntry]
    truncated: bool


async def get_removal_impact(session: AsyncSession, module: Module, max_depth: int = 10) -> RemovalImpact:
    """Every other module that would break if `module` were disabled or
    removed -- the reverse of what get_module_dependency_graph walks forward
    (app/api/routes/modules.py), reusing the same three edge kinds and the
    same FQCN-resolution pattern for di.xml preferences/plugins (for_type/
    intercepted_type are bare strings, not foreign keys to Module -- see
    that function's own docstring). Unlike find_orphaned_disabled_modules
    (app/search/cleanup_candidates.py, fleet-wide, zero-incoming-edge scan),
    this is a named module's full transitive blast radius -- every real
    dependent counts regardless of its own enabled state.

    Each hop only expands from the *previous* hop's newly-discovered modules
    (not the whole visited set), so an already-seen module's own edges are
    never re-walked.
    """
    visited_ids = {module.id}
    entries: list[RemovalImpactEntry] = []
    frontier: dict[int, Module] = {module.id: module}
    truncated = False

    def observe(discovered: dict[int, tuple[Module, str]], target: Module, relation: str) -> None:
        if target.id not in visited_ids and target.id not in discovered:
            discovered[target.id] = (target, relation)

    for hop in range(1, max_depth + 1):
        if not frontier:
            break

        discovered: dict[int, tuple[Module, str]] = {}

        for target_module in frontier.values():
            reverse_dependents = (
                await session.execute(
                    select(Module)
                    .join(ModuleDependency, ModuleDependency.module_id == Module.id)
                    .where(ModuleDependency.depends_on_name == target_module.name)
                )
            ).scalars().all()
            for source_module in reverse_dependents:
                observe(discovered, source_module, "depends_on")

            own_fqcns = (
                await session.scalars(select(PhpClass.fqcn).where(PhpClass.module_id == target_module.id))
            ).all()
            if not own_fqcns:
                continue

            reverse_preferences = (
                await session.execute(
                    select(Module)
                    .join(DiPreference, DiPreference.module_id == Module.id)
                    .where(DiPreference.for_type.in_(own_fqcns))
                )
            ).scalars().all()
            for source_module in reverse_preferences:
                observe(discovered, source_module, "overrides")

            reverse_plugins = (
                await session.execute(
                    select(Module)
                    .join(DiPlugin, DiPlugin.module_id == Module.id)
                    .where(DiPlugin.intercepted_type.in_(own_fqcns))
                )
            ).scalars().all()
            for source_module in reverse_plugins:
                observe(discovered, source_module, "plugins")

        if not discovered:
            break

        next_frontier: dict[int, Module] = {}
        for discovered_id, (discovered_module, relation) in discovered.items():
            if len(visited_ids) >= _MAX_IMPACT_MODULES:
                truncated = True
                break
            visited_ids.add(discovered_id)
            next_frontier[discovered_id] = discovered_module
            entries.append(
                RemovalImpactEntry(
                    module_id=discovered_module.id,
                    module_name=discovered_module.name,
                    hop=hop,
                    relation=relation,
                )
            )
        frontier = next_frontier

    return RemovalImpact(entries=entries, truncated=truncated)
