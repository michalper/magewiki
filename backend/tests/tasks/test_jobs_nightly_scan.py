import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.models import Module
from app.tasks import jobs as jobs_module
from app.tasks.jobs import _NIGHTLY_SCAN_CONCURRENCY, nightly_scan_all


async def _make_module(session, repo_root: str, name: str) -> Module:
    module = Module(
        repo_root=repo_root,
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


@pytest.mark.asyncio
async def test_nightly_scan_all_rescans_each_distinct_repo_once(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"/tmp/nightly-test-a-{suffix}"
    repo_b = f"/tmp/nightly-test-b-{suffix}"

    await _make_module(db_session, repo_a, f"ModuleA1_{suffix}")
    await _make_module(db_session, repo_a, f"ModuleA2_{suffix}")
    await _make_module(db_session, repo_b, f"ModuleB_{suffix}")
    await db_session.commit()

    calls: list[str] = []

    async def fake_scan_repository_job(ctx, repo_root):
        calls.append(repo_root)

    monkeypatch.setattr(jobs_module, "scan_repository_job", fake_scan_repository_job)

    await nightly_scan_all({})

    my_calls = [c for c in calls if c in (repo_a, repo_b)]
    assert sorted(my_calls) == sorted([repo_a, repo_b])  # repo_a called once despite 2 modules

    await db_session.execute(delete(Module).where(Module.repo_root.in_([repo_a, repo_b])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_nightly_scan_all_continues_after_one_repo_fails(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    bad_repo = f"/tmp/nightly-test-bad-{suffix}"
    good_repo = f"/tmp/nightly-test-good-{suffix}"

    await _make_module(db_session, bad_repo, f"BadModule_{suffix}")
    await _make_module(db_session, good_repo, f"GoodModule_{suffix}")
    await db_session.commit()

    calls: list[str] = []

    async def fake_scan_repository_job(ctx, repo_root):
        calls.append(repo_root)
        if repo_root == bad_repo:
            raise RuntimeError("disk gone")

    monkeypatch.setattr(jobs_module, "scan_repository_job", fake_scan_repository_job)

    await nightly_scan_all({})  # must not raise

    assert bad_repo in calls
    assert good_repo in calls

    await db_session.execute(delete(Module).where(Module.repo_root.in_([bad_repo, good_repo])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_nightly_scan_all_runs_repos_concurrently_up_to_the_cap(db_session, monkeypatch):
    """Found by a whole-project code review: repos used to be scanned one at a
    time despite each having its own independent advisory lock and DB
    session -- verify real overlap in flight, not just that every repo
    eventually gets called, and that it never exceeds the configured cap."""
    suffix = uuid.uuid4().hex[:8]
    repo_count = _NIGHTLY_SCAN_CONCURRENCY + 2
    repos = [f"/tmp/nightly-test-concurrency-{suffix}-{i}" for i in range(repo_count)]
    for i, repo in enumerate(repos):
        await _make_module(db_session, repo, f"ConcurrencyModule_{suffix}_{i}")
    await db_session.commit()

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake_scan_repository_job(ctx, repo_root):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0)  # yield so other scheduled scans can actually overlap
        async with lock:
            in_flight -= 1

    monkeypatch.setattr(jobs_module, "scan_repository_job", fake_scan_repository_job)

    await nightly_scan_all({})

    assert max_in_flight > 1  # genuine overlap, not a sequential loop
    assert max_in_flight <= _NIGHTLY_SCAN_CONCURRENCY

    await db_session.execute(delete(Module).where(Module.repo_root.in_(repos)))
    await db_session.commit()
