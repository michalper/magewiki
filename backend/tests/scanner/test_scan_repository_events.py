import shutil
from pathlib import Path

import pytest

from app.db import async_session_factory
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository_events


def _make_module(repo_root: Path, demo_module_path: Path, name: str) -> None:
    module_dir = repo_root / "app" / "code" / "Vendor" / name
    shutil.copytree(demo_module_path, module_dir)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="Vendor_{name}"/></config>'
    )


@pytest.mark.asyncio
async def test_yields_discovered_then_one_module_event_each_then_done(
    tmp_path: Path, demo_module_path: Path, db_session
):
    """Live progress exists specifically so a streaming caller (POST
    /scan/stream) can show a progress bar/log instead of one multi-minute
    blocking request with no feedback — this locks in the event contract
    the frontend depends on.
    """
    repo_root = tmp_path / "repo"
    _make_module(repo_root, demo_module_path, "One")
    _make_module(repo_root, demo_module_path, "Two")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]

    assert events[0] == {"event": "discovered", "total": 2}
    module_events = [e for e in events if e["event"] == "module"]
    # find_modules() doesn't guarantee discovery order (confirmed in CI,
    # where filesystem iteration order differs from local) — only the
    # sequential 1..N indexing is actually promised, not which name comes
    # first.
    assert {e["name"] for e in module_events} == {"Vendor_One", "Vendor_Two"}
    assert [e["index"] for e in module_events] == [1, 2]
    assert all(e["total"] == 2 and e["status"] == "created" for e in module_events)
    assert events[-1]["event"] == "done"
    assert events[-1]["result"].modules_created == 2


@pytest.mark.asyncio
async def test_a_second_concurrent_scan_of_the_same_repo_is_rejected(
    tmp_path: Path, demo_module_path: Path, db_session
):
    """The whole-scan mutual-exclusion lock used to ride on one transaction's
    lifetime (pg_try_advisory_xact_lock) — per-module commits mean that no
    longer works, so this is now a session-level pg_try_advisory_lock held
    for the generator's whole lifetime instead. pg_try_advisory_lock is
    reentrant *within* a session (the same session re-acquiring its own lock
    always succeeds), so this must use two genuinely separate sessions —
    db_session plus a second one opened directly — to actually exercise
    cross-session contention, not just call the generator twice on the same
    connection.
    """
    repo_root = tmp_path / "repo"
    _make_module(repo_root, demo_module_path, "One")

    first = scan_repository_events(str(repo_root), db_session)
    await first.__anext__()  # "discovered" — lock is acquired before this yields

    async with async_session_factory() as second_session:
        with pytest.raises(ScanAlreadyInProgressError):
            async for _ in scan_repository_events(str(repo_root), second_session):
                pass

    # Drain the first generator so its `finally` releases the lock before the
    # test's db_session fixture tears down.
    async for _ in first:
        pass


@pytest.mark.asyncio
async def test_the_lock_is_actually_released_after_a_multi_module_scan_commits_several_times(
    tmp_path: Path, demo_module_path: Path, db_session
):
    """Regression test for a real bug: a session-level advisory lock is tied
    to one specific physical connection, but AsyncSession checks out a *new*
    connection from the pool each time it begins a transaction (autobegin
    after every commit()) — and this generator commits once per module. The
    lock was being acquired through `session` on one connection and "released"
    through `session` later on a different one: pg_advisory_unlock silently
    returned false (not actually held by the caller) and the lock leaked
    forever onto the original connection, now idle in the pool. Confirmed in
    production: every test after the first multi-module scan in a session
    failed with ScanAlreadyInProgressError, and the exact same thing happened
    in CI with zero concurrent activity to blame. A single-module scan (the
    other tests in this file) never exercises more than one commit, so it
    couldn't have caught this — this one needs >= 2 modules specifically.
    """
    repo_root = tmp_path / "repo"
    _make_module(repo_root, demo_module_path, "One")
    _make_module(repo_root, demo_module_path, "Two")

    async for _ in scan_repository_events(str(repo_root), db_session):
        pass

    async with async_session_factory() as second_session:
        events = [event async for event in scan_repository_events(str(repo_root), second_session)]

    assert events[-1]["event"] == "done"
    assert events[-1]["result"].modules_updated == 2
