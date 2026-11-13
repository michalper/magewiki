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
    by_time = {p.scanned_at: p.total_findings for p in points}

    total_after_a1 = by_time[t0]
    total_after_b1 = by_time[t0 + timedelta(seconds=1)]
    total_after_a2 = by_time[t0 + timedelta(seconds=2)]

    assert total_after_b1 - total_after_a1 == 3  # module_b's own 3 findings added
    assert total_after_a2 - total_after_b1 == -2  # module_a's own total dropped 3 -> 1

    # This repo_root/state ("up_to_date") makes these two modules real
    # fleet-wide "already-analyzed" members -- other unrelated fleet-wide
    # tests (e.g. an embedding-model change's own "N modules affected"
    # count) would otherwise count them too, since db_session never rolls
    # back between tests.
    await db_session.execute(delete(Module).where(Module.id.in_([module_a.id, module_b.id])))
    await db_session.commit()
