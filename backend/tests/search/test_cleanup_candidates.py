import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.models import (
    DiPlugin,
    DiPreference,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
)
from app.search.cleanup_candidates import find_orphaned_disabled_modules


async def _make_module(session, suffix: str, *, name: str | None = None, enabled: bool = False) -> Module:
    module = Module(
        repo_root=f"/tmp/cleanup-candidates-test-{suffix}",
        name=name or f"CleanupTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        enabled=enabled,
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
async def test_flags_a_disabled_module_with_no_incoming_edges(db_session):
    suffix = uuid.uuid4().hex[:8]
    orphan = await _make_module(db_session, suffix, name=f"Orphan_{suffix}")
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, orphan)

    assert any(o.module_id == orphan.id for o in result)


@pytest.mark.asyncio
async def test_excludes_an_enabled_module_even_with_no_incoming_edges(db_session):
    suffix = uuid.uuid4().hex[:8]
    enabled_orphan = await _make_module(db_session, suffix, name=f"EnabledOrphan_{suffix}", enabled=True)
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, enabled_orphan)

    assert all(o.module_id != enabled_orphan.id for o in result)


@pytest.mark.asyncio
async def test_excludes_a_disabled_module_something_still_sequences_after(db_session):
    suffix = uuid.uuid4().hex[:8]
    referenced = await _make_module(db_session, suffix, name=f"Referenced_{suffix}")
    dependent = await _make_module(db_session, f"{suffix}-dep", name=f"Dependent_{suffix}", enabled=True)
    db_session.add(ModuleDependency(module_id=dependent.id, depends_on_name=referenced.name))
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, referenced, dependent)

    assert all(o.module_id != referenced.id for o in result)


@pytest.mark.asyncio
async def test_excludes_a_disabled_module_overridden_by_a_di_preference(db_session):
    suffix = uuid.uuid4().hex[:8]
    overridden = await _make_module(db_session, suffix, name=f"Overridden_{suffix}")
    overrider = await _make_module(db_session, f"{suffix}-over", name=f"Overrider_{suffix}", enabled=True)
    fqcn = f"Vendor\\Overridden\\Model\\Thing_{suffix}"
    db_session.add(
        PhpClass(
            module_id=overridden.id, fqcn=fqcn, class_name="Thing", kind="class", file_path="Model/Thing.php"
        )
    )
    db_session.add(DiPreference(module_id=overrider.id, for_type=fqcn, preference_type="Vendor\\Overrider\\Model\\Thing"))
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, overridden, overrider)

    assert all(o.module_id != overridden.id for o in result)


@pytest.mark.asyncio
async def test_excludes_a_disabled_module_targeted_by_a_di_plugin(db_session):
    suffix = uuid.uuid4().hex[:8]
    plugged = await _make_module(db_session, suffix, name=f"Plugged_{suffix}")
    plugger = await _make_module(db_session, f"{suffix}-plug", name=f"Plugger_{suffix}", enabled=True)
    fqcn = f"Vendor\\Plugged\\Model\\Thing_{suffix}"
    db_session.add(
        PhpClass(module_id=plugged.id, fqcn=fqcn, class_name="Thing", kind="class", file_path="Model/Thing.php")
    )
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
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, plugged, plugger)

    assert all(o.module_id != plugged.id for o in result)


@pytest.mark.asyncio
async def test_attaches_finding_counts_as_context(db_session):
    suffix = uuid.uuid4().hex[:8]
    orphan = await _make_module(db_session, suffix, name=f"OrphanWithFindings_{suffix}")
    db_session.add(
        ModuleQualityFinding(module_id=orphan.id, check_type="hardcoded_secret", severity="blocking", message="m")
    )
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, orphan)

    entry = next(o for o in result if o.module_id == orphan.id)
    assert entry.finding_counts == {"hardcoded_secret": 1}


@pytest.mark.asyncio
async def test_a_module_with_no_findings_has_an_empty_finding_counts_dict(db_session):
    suffix = uuid.uuid4().hex[:8]
    orphan = await _make_module(db_session, suffix, name=f"OrphanNoFindings_{suffix}")
    await db_session.commit()

    try:
        result = await find_orphaned_disabled_modules(db_session, limit=500)
    finally:
        await _cleanup(db_session, orphan)

    entry = next(o for o in result if o.module_id == orphan.id)
    assert entry.finding_counts == {}
