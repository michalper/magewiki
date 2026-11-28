import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

import app.search.removal_impact as removal_impact_module
from app.models import DiPlugin, DiPreference, Module, ModuleDependency, PhpClass
from app.search.removal_impact import get_removal_impact


async def _make_module(session, suffix: str, *, name: str | None = None) -> Module:
    module = Module(
        repo_root=f"/tmp/removal-impact-test-{suffix}",
        name=name or f"RemovalImpactTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


async def _cleanup(session, *modules: Module) -> None:
    await session.execute(delete(Module).where(Module.id.in_([m.id for m in modules])))
    await session.commit()


@pytest.mark.asyncio
async def test_a_module_with_no_dependents_has_no_impact(db_session):
    suffix = uuid.uuid4().hex[:8]
    lonely = await _make_module(db_session, suffix)
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, lonely)
    finally:
        await _cleanup(db_session, lonely)

    assert impact.entries == []
    assert impact.truncated is False


@pytest.mark.asyncio
async def test_a_direct_module_xml_dependent_is_found_at_hop_1(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = await _make_module(db_session, suffix, name=f"Target_{suffix}")
    dependent = await _make_module(db_session, f"{suffix}-dep", name=f"Dependent_{suffix}")
    db_session.add(ModuleDependency(module_id=dependent.id, depends_on_name=target.name))
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, target)
    finally:
        await _cleanup(db_session, target, dependent)

    assert len(impact.entries) == 1
    entry = impact.entries[0]
    assert entry.module_id == dependent.id
    assert entry.hop == 1
    assert entry.relation == "depends_on"


@pytest.mark.asyncio
async def test_a_direct_di_preference_dependent_is_found_at_hop_1(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = await _make_module(db_session, suffix, name=f"Target_{suffix}")
    overrider = await _make_module(db_session, f"{suffix}-over", name=f"Overrider_{suffix}")
    fqcn = f"Vendor\\Target\\Model\\Thing_{suffix}"
    db_session.add(PhpClass(module_id=target.id, fqcn=fqcn, class_name="Thing", kind="class", file_path="Model/Thing.php"))
    db_session.add(DiPreference(module_id=overrider.id, for_type=fqcn, preference_type="Vendor\\Overrider\\Model\\Thing"))
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, target)
    finally:
        await _cleanup(db_session, target, overrider)

    assert len(impact.entries) == 1
    entry = impact.entries[0]
    assert entry.module_id == overrider.id
    assert entry.hop == 1
    assert entry.relation == "overrides"


@pytest.mark.asyncio
async def test_a_direct_di_plugin_dependent_is_found_at_hop_1(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = await _make_module(db_session, suffix, name=f"Target_{suffix}")
    plugger = await _make_module(db_session, f"{suffix}-plug", name=f"Plugger_{suffix}")
    fqcn = f"Vendor\\Target\\Model\\Thing_{suffix}"
    db_session.add(PhpClass(module_id=target.id, fqcn=fqcn, class_name="Thing", kind="class", file_path="Model/Thing.php"))
    db_session.add(
        DiPlugin(
            module_id=plugger.id,
            intercepted_type=fqcn,
            plugin_name="thing_plugin",
            plugin_class="Vendor\\Plugger\\Plugin\\ThingPlugin",
        )
    )
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, target)
    finally:
        await _cleanup(db_session, target, plugger)

    assert len(impact.entries) == 1
    entry = impact.entries[0]
    assert entry.module_id == plugger.id
    assert entry.hop == 1
    assert entry.relation == "plugins"


@pytest.mark.asyncio
async def test_a_transitive_dependent_is_found_at_hop_2(db_session):
    # C <- B <- A (A depends on B, B depends on C) -- removing C impacts B at
    # hop 1 and A at hop 2.
    suffix = uuid.uuid4().hex[:8]
    module_c = await _make_module(db_session, suffix, name=f"C_{suffix}")
    module_b = await _make_module(db_session, f"{suffix}-b", name=f"B_{suffix}")
    module_a = await _make_module(db_session, f"{suffix}-a", name=f"A_{suffix}")
    db_session.add(ModuleDependency(module_id=module_b.id, depends_on_name=module_c.name))
    db_session.add(ModuleDependency(module_id=module_a.id, depends_on_name=module_b.name))
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, module_c)
    finally:
        await _cleanup(db_session, module_c, module_b, module_a)

    by_id = {e.module_id: e for e in impact.entries}
    assert by_id[module_b.id].hop == 1
    assert by_id[module_a.id].hop == 2


@pytest.mark.asyncio
async def test_hitting_the_node_cap_truncates_and_stops_further_expansion(db_session, monkeypatch):
    # _MAX_IMPACT_MODULES=1 means visited_ids (seeded with the target itself)
    # is already at the cap before hop 1 even starts -- the first discovered
    # dependent trips truncation immediately, next_frontier stays empty, and
    # hop 2's own "frontier is empty" check is what actually stops the loop.
    monkeypatch.setattr(removal_impact_module, "_MAX_IMPACT_MODULES", 1)
    suffix = uuid.uuid4().hex[:8]
    target = await _make_module(db_session, suffix, name=f"Target_{suffix}")
    dependent = await _make_module(db_session, f"{suffix}-dep", name=f"Dependent_{suffix}")
    db_session.add(ModuleDependency(module_id=dependent.id, depends_on_name=target.name))
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, target, max_depth=5)
    finally:
        await _cleanup(db_session, target, dependent)

    assert impact.entries == []
    assert impact.truncated is True


@pytest.mark.asyncio
async def test_max_depth_stops_expansion_before_a_deeper_real_dependent(db_session):
    # Same C <- B <- A chain, but max_depth=1 should only surface B, not A.
    suffix = uuid.uuid4().hex[:8]
    module_c = await _make_module(db_session, suffix, name=f"C_{suffix}")
    module_b = await _make_module(db_session, f"{suffix}-b", name=f"B_{suffix}")
    module_a = await _make_module(db_session, f"{suffix}-a", name=f"A_{suffix}")
    db_session.add(ModuleDependency(module_id=module_b.id, depends_on_name=module_c.name))
    db_session.add(ModuleDependency(module_id=module_a.id, depends_on_name=module_b.name))
    await db_session.commit()

    try:
        impact = await get_removal_impact(db_session, module_c, max_depth=1)
    finally:
        await _cleanup(db_session, module_c, module_b, module_a)

    impacted_ids = {e.module_id for e in impact.entries}
    assert impacted_ids == {module_b.id}
