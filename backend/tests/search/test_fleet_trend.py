import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models import Module, ModuleHistorySnapshot
from app.search.fleet_trend import get_fleet_trend


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/fleet-trend-test-{suffix}",
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


@pytest.mark.asyncio
async def test_fleet_trend_carries_each_modules_last_known_total_forward(db_session):
    # get_fleet_trend is deliberately fleet-wide, and db_session never rolls
    # back between tests (same reasoning as find_similar_modules's own test
    # file), so absolute totals here are unknowable -- this asserts on
    # *deltas* between two of this test's own uniquely-timestamped points
    # instead, which hold regardless of whatever other tests have already
    # committed.
    suffix = uuid.uuid4().hex[:8]
    # A real, microsecond-unique anchor far from any other test's timestamps.
    t0 = datetime.now(UTC) + timedelta(days=36500, microseconds=int(suffix, 16) % 1_000_000)

    module_a = await _make_module(db_session, f"{suffix}-a")
    module_b = await _make_module(db_session, f"{suffix}-b")

    db_session.add_all(
        [
            ModuleHistorySnapshot(
                module_id=module_a.id,
                scanned_at=t0,
                current_hash="hash-a1",
                state="up_to_date",
                enabled=True,
                finding_counts={"phpstan_error": 3},
            ),
            ModuleHistorySnapshot(
                module_id=module_b.id,
                scanned_at=t0 + timedelta(seconds=1),
                current_hash="hash-b1",
                state="up_to_date",
                enabled=True,
                finding_counts={"hardcoded_secret": 2, "security_advisory": 1},
            ),
            # module_a's own total drops from 3 to 1 -- carried forward, not
            # replaced, so this point's fleet total reflects both modules'
            # latest known values (1 + 3 = 4), not just this one event's own.
            ModuleHistorySnapshot(
                module_id=module_a.id,
                scanned_at=t0 + timedelta(seconds=2),
                current_hash="hash-a2",
                state="up_to_date",
                enabled=True,
                finding_counts={"phpstan_error": 1},
            ),
        ]
    )
    await db_session.commit()

    points = await get_fleet_trend(db_session)
    by_time = {p.scanned_at: p for p in points}

    point_after_a1 = by_time[t0]
    point_after_b1 = by_time[t0 + timedelta(seconds=1)]
    point_after_a2 = by_time[t0 + timedelta(seconds=2)]

    assert point_after_b1.total_findings - point_after_a1.total_findings == 3  # module_b's 3 findings added
    assert point_after_a2.total_findings - point_after_b1.total_findings == -2  # module_a's total dropped 3 -> 1

    # total_findings is always the derived sum of counts -- an invariant, not
    # an absolute value, so this holds regardless of what else is in the DB.
    for point in (point_after_a1, point_after_b1, point_after_a2):
        assert point.total_findings == sum(point.counts.values())

    # counts carries the same per-check_type breakdown forward as deltas --
    # module_b's own two check_types both showed up, and module_a's own
    # phpstan_error dropped by exactly 2 (3 -> 1), same as the total above.
    assert point_after_b1.counts.get("hardcoded_secret", 0) - point_after_a1.counts.get("hardcoded_secret", 0) == 2
    assert point_after_b1.counts.get("security_advisory", 0) - point_after_a1.counts.get("security_advisory", 0) == 1
    assert point_after_a2.counts.get("phpstan_error", 0) - point_after_b1.counts.get("phpstan_error", 0) == -2

    # This repo_root/state ("up_to_date") makes these two modules real
    # fleet-wide "already-analyzed" members -- other unrelated fleet-wide
    # tests (e.g. an embedding-model change's own "N modules affected"
    # count) would otherwise count them too, since db_session never rolls
    # back between tests.
    await db_session.execute(delete(Module).where(Module.id.in_([module_a.id, module_b.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_fleet_trend_drops_a_category_from_counts_once_it_reaches_zero(db_session):
    suffix = uuid.uuid4().hex[:8]
    t0 = datetime.now(UTC) + timedelta(days=36510, microseconds=int(suffix, 16) % 1_000_000)
    module = await _make_module(db_session, suffix)
    # finding_counts is free-form JSONB (no CHECK constraint, unlike
    # ModuleQualityFinding.check_type), so a synthetic, test-unique key here
    # -- not a real check_type like "hardcoded_secret" -- guarantees no
    # other test's real fixture data (e.g. Phase 18's own real-secret-scan
    # test) also contributes to this same fleet-wide bucket. A real
    # check_type's fleet-wide total never actually reaches 0 across the
    # whole suite, so asserting *absence* (not just a delta) needs a key
    # nothing else could possibly touch.
    check_type = f"test-only-check-{suffix}"

    db_session.add_all(
        [
            ModuleHistorySnapshot(
                module_id=module.id,
                scanned_at=t0,
                current_hash="hash-1",
                state="up_to_date",
                enabled=True,
                finding_counts={check_type: 5},
            ),
            # The finding got fixed -- finding_counts no longer mentions this
            # check_type at all for this module, same shape history.py's own
            # write path produces for a module with no more findings of a
            # given type.
            ModuleHistorySnapshot(
                module_id=module.id,
                scanned_at=t0 + timedelta(seconds=1),
                current_hash="hash-2",
                state="up_to_date",
                enabled=True,
                finding_counts={},
            ),
        ]
    )
    await db_session.commit()

    points = await get_fleet_trend(db_session)
    by_time = {p.scanned_at: p for p in points}

    assert by_time[t0].counts.get(check_type, 0) == 5
    # Not present with value 0 -- absent entirely, per the docstring's own
    # "categories with real, current findings" contract.
    assert check_type not in by_time[t0 + timedelta(seconds=1)].counts

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
