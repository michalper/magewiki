import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Module, ModuleHistorySnapshot
from app.tasks.jobs import prune_module_history


async def _make_module(session, name: str) -> Module:
    module = Module(
        repo_root=f"/tmp/prune-test-{name}",
        name=name,
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{name}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


def _snapshot(module_id: int, scanned_at: datetime, current_hash: str) -> ModuleHistorySnapshot:
    return ModuleHistorySnapshot(
        module_id=module_id,
        scanned_at=scanned_at,
        current_hash=current_hash,
        state="up_to_date",
        enabled=True,
        finding_counts={},
    )


@pytest.mark.asyncio
async def test_prune_deletes_old_snapshots_but_keeps_the_oldest_as_a_baseline(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, f"Vendor_{suffix}")

    now = datetime.now(UTC)
    oldest = _snapshot(module.id, now - timedelta(days=800), "hash-oldest")
    also_old = _snapshot(module.id, now - timedelta(days=500), "hash-also-old")
    recent = _snapshot(module.id, now - timedelta(days=10), "hash-recent")
    db_session.add_all([oldest, also_old, recent])
    await db_session.commit()

    await prune_module_history({})

    remaining = (
        await db_session.scalars(
            select(ModuleHistorySnapshot)
            .where(ModuleHistorySnapshot.module_id == module.id)
            .order_by(ModuleHistorySnapshot.scanned_at)
        )
    ).all()
    assert [row.current_hash for row in remaining] == ["hash-oldest", "hash-recent"]


@pytest.mark.asyncio
async def test_prune_leaves_a_single_old_baseline_snapshot_alone(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, f"Vendor_{suffix}")

    only = _snapshot(module.id, datetime.now(UTC) - timedelta(days=800), "hash-only")
    db_session.add(only)
    await db_session.commit()

    await prune_module_history({})

    remaining = (
        await db_session.scalars(select(ModuleHistorySnapshot).where(ModuleHistorySnapshot.module_id == module.id))
    ).all()
    assert len(remaining) == 1
