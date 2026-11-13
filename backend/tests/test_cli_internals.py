from pathlib import Path

import pytest
from sqlalchemy import select, update

from app import cli
from app.cli import (
    _run_resume_budget,
    _run_resume_failed,
    _run_resume_stuck,
    _run_scan,
    _run_seed_packagist_cache,
    main,
)
from app.models import FileHash, Module
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository
from app.scanner.packagist_cache import get_cached
from app.tasks.queue import get_arq_pool
from tests.conftest import delete_module_if_present


@pytest.mark.asyncio
async def test_run_scan_prints_results_and_returns_0(demo_store_path: Path, db_session, capsys):
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    exit_code = await _run_scan(repo_root)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Scanned {repo_root}" in out
    assert "modules_found=1" in out
    assert "Vendor_Module" in out


@pytest.mark.asyncio
async def test_run_scan_returns_1_when_already_in_progress(monkeypatch, capsys):
    async def _raise(repo_root, session):
        raise ScanAlreadyInProgressError(f"a scan of {repo_root} is already in progress")

    monkeypatch.setattr(cli, "scan_repository", _raise)

    exit_code = await _run_scan("/some/path")

    assert exit_code == 1
    assert "already in progress" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_scan_returns_1_when_a_module_errored(monkeypatch, capsys):
    from dataclasses import dataclass, field

    @dataclass
    class _FakeOutcome:
        name: str = "Vendor_Broken"
        status: str = "error"
        state: str = "failed"
        classes: int = 0
        plugins: int = 0
        observers: int = 0
        files_added: int = 0
        files_changed: int = 0
        files_removed: int = 0
        warnings: list = field(default_factory=lambda: ["something went wrong"])

    @dataclass
    class _FakeResult:
        repo_root: str = "/some/path"
        modules_found: int = 1
        modules_created: int = 0
        modules_updated: int = 1
        classes_total: int = 0
        plugins_total: int = 0
        observers_total: int = 0
        tasks_enqueued: int = 0
        warnings: list = field(default_factory=list)
        modules: list = field(default_factory=lambda: [_FakeOutcome()])

    async def _fake_scan(repo_root, session):
        return _FakeResult()

    monkeypatch.setattr(cli, "scan_repository", _fake_scan)

    exit_code = await _run_scan("/some/path")

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "warning: something went wrong" in out


@pytest.mark.asyncio
async def test_run_scan_prints_top_level_warnings(monkeypatch, capsys):
    from dataclasses import dataclass, field

    @dataclass
    class _FakeResult:
        repo_root: str = "/some/path"
        modules_found: int = 0
        modules_created: int = 0
        modules_updated: int = 0
        classes_total: int = 0
        plugins_total: int = 0
        observers_total: int = 0
        tasks_enqueued: int = 0
        warnings: list = field(default_factory=lambda: ["a store-level issue"])
        modules: list = field(default_factory=list)

    async def _fake_scan(repo_root, session):
        return _FakeResult()

    monkeypatch.setattr(cli, "scan_repository", _fake_scan)

    exit_code = await _run_scan("/some/path")

    assert exit_code == 0
    assert "warning: a store-level issue" in capsys.readouterr().out


async def _scan_demo(demo_store_path: Path, db_session) -> Module:
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)
    return await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))


@pytest.mark.asyncio
async def test_run_resume_budget_reports_when_nothing_is_paused(db_session, capsys):
    await db_session.execute(update(Module).where(Module.state == "paused_budget").values(state="up_to_date"))
    await db_session.commit()

    assert await _run_resume_budget(None) == 0
    assert "No modules in paused_budget state." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_resume_budget_resumes_a_paused_module(demo_store_path: Path, db_session):
    module = await _scan_demo(demo_store_path, db_session)
    await db_session.execute(update(Module).where(Module.id == module.id).values(state="paused_budget"))
    await db_session.commit()

    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    expected_job_id = f"analyze:{module.id}:etc/module.xml:{file_hash.content_hash}"

    assert await _run_resume_budget(None) == 0

    pool = await get_arq_pool()
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert expected_job_id in queued_ids


@pytest.mark.asyncio
async def test_run_resume_budget_filters_by_repo_root(demo_store_path: Path, demo_module_path: Path, db_session):
    module = await _scan_demo(demo_store_path, db_session)
    await db_session.execute(update(Module).where(Module.id == module.id).values(state="paused_budget"))
    await db_session.commit()

    assert await _run_resume_budget(str(demo_module_path)) == 0  # no match under this unrelated root

    await db_session.refresh(module)
    assert module.state == "paused_budget"  # untouched -- the filter excluded it


@pytest.mark.asyncio
async def test_run_resume_failed_filters_by_repo_root(demo_store_path: Path, db_session):
    module = await _scan_demo(demo_store_path, db_session)
    await db_session.execute(update(Module).where(Module.id == module.id).values(state="failed"))
    await db_session.commit()

    assert await _run_resume_failed(module.repo_root) == 0

    pool = await get_arq_pool()
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert f"analyze:{module.id}:etc/module.xml:{file_hash.content_hash}" in queued_ids


@pytest.mark.asyncio
async def test_run_resume_stuck_filters_by_repo_root(demo_store_path: Path, db_session):
    module = await _scan_demo(demo_store_path, db_session)
    await db_session.execute(update(FileHash).where(FileHash.module_id == module.id).values(analyzed=True))
    await db_session.execute(
        update(Module).where(Module.id == module.id).values(state="analyzing", pending_file_count=0)
    )
    await db_session.commit()

    assert await _run_resume_stuck(module.repo_root) == 0

    pool = await get_arq_pool()
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert f"synthesize:{module.id}:{module.current_hash}" in queued_ids


@pytest.mark.asyncio
async def test_run_seed_packagist_cache_writes_a_real_row(db_session, capsys):
    exit_code = await _run_seed_packagist_cache(
        "advisories:vendor/fake-pkg", '{"advisories": {"vendor/fake-pkg": []}}'
    )

    assert exit_code == 0
    assert "Seeded packagist_cache[advisories:vendor/fake-pkg]" in capsys.readouterr().out
    cached = await get_cached(db_session, "advisories:vendor/fake-pkg")
    assert cached == {"advisories": {"vendor/fake-pkg": []}}


def test_main_dispatches_scan(monkeypatch):
    seen = {}

    async def _fake_run_scan(path):
        seen["path"] = path
        return 0

    monkeypatch.setattr(cli, "_run_scan", _fake_run_scan)

    assert main(["scan", "/a/path"]) == 0
    assert seen["path"] == "/a/path"


def test_main_dispatches_resume_budget(monkeypatch):
    seen = {}

    async def _fake(repo_root):
        seen["repo_root"] = repo_root
        return 0

    monkeypatch.setattr(cli, "_run_resume_budget", _fake)

    assert main(["resume-budget", "/a/path"]) == 0
    assert seen["repo_root"] == "/a/path"


def test_main_dispatches_resume_budget_with_no_repo_root(monkeypatch):
    seen = {}

    async def _fake(repo_root):
        seen["repo_root"] = repo_root
        return 0

    monkeypatch.setattr(cli, "_run_resume_budget", _fake)

    assert main(["resume-budget"]) == 0
    assert seen["repo_root"] is None


def test_main_dispatches_resume_failed(monkeypatch):
    seen = {}

    async def _fake(repo_root):
        seen["called"] = True
        return 0

    monkeypatch.setattr(cli, "_run_resume_failed", _fake)

    assert main(["resume-failed"]) == 0
    assert seen["called"] is True


def test_main_dispatches_resume_stuck(monkeypatch):
    seen = {}

    async def _fake(repo_root):
        seen["called"] = True
        return 0

    monkeypatch.setattr(cli, "_run_resume_stuck", _fake)

    assert main(["resume-stuck"]) == 0
    assert seen["called"] is True


def test_main_dispatches_seed_packagist_cache(monkeypatch):
    seen = {}

    async def _fake(cache_key, response_json):
        seen["cache_key"] = cache_key
        seen["response_json"] = response_json
        return 0

    monkeypatch.setattr(cli, "_run_seed_packagist_cache", _fake)

    assert main(["seed-packagist-cache", "advisories:vendor/pkg", '{"advisories": {}}']) == 0
    assert seen["cache_key"] == "advisories:vendor/pkg"
    assert seen["response_json"] == '{"advisories": {}}'


def test_main_requires_a_subcommand():
    with pytest.raises(SystemExit):
        main([])


def test_main_propagates_a_nonzero_exit_code(monkeypatch):
    async def _fake_run_scan(path):
        return 1

    monkeypatch.setattr(cli, "_run_scan", _fake_run_scan)

    assert main(["scan", "/a/path"]) == 1
