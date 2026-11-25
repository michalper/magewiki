import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.models import Module
from app.search.module_overlap import find_module_overlap


def _module(
    repo_root: str, name: str, current_hash: str, enabled: bool, setup_version: str | None = None
) -> Module:
    return Module(
        repo_root=repo_root,
        name=name,
        composer_name=f"vendor/{name.lower()}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=current_hash,
        setup_version=setup_version,
        enabled=enabled,
        has_readme=False,
        has_tests=False,
        last_scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def _cleanup(session, *modules: Module) -> None:
    await session.execute(delete(Module).where(Module.id.in_([m.id for m in modules])))
    await session.commit()


@pytest.mark.asyncio
async def test_a_module_present_under_only_one_repo_root_is_excluded(db_session):
    suffix = uuid.uuid4().hex[:8]
    unique = _module(f"/tmp/overlap-a-{suffix}", f"Unique_{suffix}", "hash-only", True, "1.0.0")
    db_session.add(unique)
    await db_session.commit()

    try:
        result = await find_module_overlap(db_session)
        assert unique.name not in {e.name for e in result}
    finally:
        await _cleanup(db_session, unique)


@pytest.mark.asyncio
async def test_a_module_with_the_same_hash_across_stores_has_no_version_drift(db_session):
    suffix = uuid.uuid4().hex[:8]
    name = f"Shared_{suffix}"
    rows = [
        _module(f"/tmp/overlap-a-{suffix}", name, "hash1", True, "2.1.3"),
        _module(f"/tmp/overlap-b-{suffix}", name, "hash1", True, "2.1.3"),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    try:
        result = await find_module_overlap(db_session)
        entry = next(e for e in result if e.name == name)
        assert entry.store_count == 2
        assert entry.version_drift is False
        assert {s.current_hash for s in entry.stores} == {"hash1"}
        assert {s.module_id for s in entry.stores} == {rows[0].id, rows[1].id}
    finally:
        await _cleanup(db_session, *rows)


@pytest.mark.asyncio
async def test_a_module_with_different_hashes_across_stores_flags_version_drift(db_session):
    suffix = uuid.uuid4().hex[:8]
    name = f"Drifted_{suffix}"
    rows = [
        _module(f"/tmp/overlap-a-{suffix}", name, "hash-old", True, "2.0.9"),
        _module(f"/tmp/overlap-b-{suffix}", name, "hash-new", True, "2.1.0"),
        _module(f"/tmp/overlap-c-{suffix}", name, "hash-new", False, "2.1.0"),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    try:
        result = await find_module_overlap(db_session)
        entry = next(e for e in result if e.name == name)
        assert entry.store_count == 3
        assert entry.version_drift is True
        assert {s.current_hash for s in entry.stores} == {"hash-old", "hash-new"}
        assert {s.setup_version for s in entry.stores} == {"2.0.9", "2.1.0"}
    finally:
        await _cleanup(db_session, *rows)
