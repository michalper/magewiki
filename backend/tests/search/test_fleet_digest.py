import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models import Module, ModuleHistorySnapshot
from app.search.fleet_digest import get_fleet_digest

# get_fleet_digest is deliberately fleet-wide (no repo_root filter), and
# db_session never rolls back between tests (same reasoning as
# tests/search/test_fleet_trend.py), so every test anchors its own window
# far enough in the future (a distinct day offset per test, plus a
# uuid-derived microsecond offset) that no other test in the suite could
# ever plant a snapshot inside it, and cleans up its own modules afterward
# so it doesn't leak into some other far-future window either.


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/fleet-digest-test-{suffix}",
        name=f"Vendor_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


def _snapshot(module_id: int, scanned_at: datetime, finding_counts: dict[str, int]) -> ModuleHistorySnapshot:
    return ModuleHistorySnapshot(
        module_id=module_id,
        scanned_at=scanned_at,
        current_hash="hash",
        state="up_to_date",
        enabled=True,
        finding_counts=finding_counts,
    )


def _anchor(day_offset: int) -> datetime:
    suffix = uuid.uuid4().hex[:8]
    return datetime.now(UTC) + timedelta(days=day_offset, microseconds=int(suffix, 16) % 1_000_000)


@pytest.mark.asyncio
async def test_a_module_with_no_snapshot_before_the_window_is_reported_as_new(db_session):
    anchor = _anchor(36520)
    module = await _make_module(db_session, f"new-{anchor.microsecond}")
    db_session.add(_snapshot(module.id, anchor, {"phpstan_error": 2}))
    await db_session.commit()

    digest = await get_fleet_digest(db_session, anchor - timedelta(hours=1))

    assert (module.id, module.name) in digest.new_modules
    assert all(c.module_id != module.id for c in digest.changed_modules)

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_module_whose_finding_count_went_up_in_the_window_is_a_changed_module(db_session):
    anchor = _anchor(36521)
    module = await _make_module(db_session, f"up-{anchor.microsecond}")
    db_session.add(_snapshot(module.id, anchor - timedelta(days=5), {"phpstan_error": 1}))
    db_session.add(_snapshot(module.id, anchor + timedelta(days=1), {"phpstan_error": 4}))
    await db_session.commit()

    digest = await get_fleet_digest(db_session, anchor)

    assert all(module_id != module.id for module_id, _ in digest.new_modules)
    change = next(c for c in digest.changed_modules if c.module_id == module.id)
    assert change.previous_total == 1
    assert change.current_total == 4

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_module_whose_finding_count_went_down_in_the_window_is_also_a_changed_module(db_session):
    anchor = _anchor(36522)
    module = await _make_module(db_session, f"down-{anchor.microsecond}")
    db_session.add(_snapshot(module.id, anchor - timedelta(days=5), {"hardcoded_secret": 3}))
    db_session.add(_snapshot(module.id, anchor + timedelta(days=1), {"hardcoded_secret": 1}))
    await db_session.commit()

    digest = await get_fleet_digest(db_session, anchor)

    change = next(c for c in digest.changed_modules if c.module_id == module.id)
    assert change.previous_total == 3
    assert change.current_total == 1

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_module_with_no_activity_in_the_window_is_silent(db_session):
    anchor = _anchor(36523)
    module = await _make_module(db_session, f"quiet-{anchor.microsecond}")
    db_session.add(_snapshot(module.id, anchor - timedelta(days=30), {"phpstan_error": 5}))
    await db_session.commit()

    digest = await get_fleet_digest(db_session, anchor)

    assert all(c.module_id != module.id for c in digest.changed_modules)
    assert all(module_id != module.id for module_id, _ in digest.new_modules)

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_window_nobody_touched_reports_nothing(db_session):
    anchor = _anchor(36524)

    digest = await get_fleet_digest(db_session, anchor)

    assert digest.new_modules == []
    assert digest.changed_modules == []
    assert digest.total_delta == 0
