from pathlib import Path

import pytest

from app.scanner import orchestrator as orchestrator_module
from app.scanner.orchestrator import _is_deadlock, scan_repository_events


class _FakeDeadlockOrig:
    sqlstate = "40P01"


class _FakeDeadlockError(Exception):
    def __init__(self) -> None:
        super().__init__("deadlock detected")
        self.orig = _FakeDeadlockOrig()


def test_is_deadlock_detects_sqlstate_40p01():
    assert _is_deadlock(_FakeDeadlockError()) is True


def test_is_deadlock_false_for_an_unrelated_error_with_no_orig():
    assert _is_deadlock(RuntimeError("boom")) is False


def test_is_deadlock_false_for_a_different_sqlstate():
    class _OtherOrig:
        sqlstate = "23505"  # unique_violation, a real but different error

    class _OtherError(Exception):
        def __init__(self) -> None:
            super().__init__("duplicate key")
            self.orig = _OtherOrig()

    assert _is_deadlock(_OtherError()) is False


def _write_module(module_dir: Path, name: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_scan_retries_a_module_once_after_a_simulated_deadlock(tmp_path: Path, db_session, monkeypatch):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A")

    real_persist_module = orchestrator_module._persist_module
    calls = {"count": 0}

    async def flaky_persist_module(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _FakeDeadlockError()
        return await real_persist_module(*args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "_persist_module", flaky_persist_module)

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")

    assert calls["count"] == 2
    assert done["result"].modules_created == 1
    assert done["result"].warnings == []


@pytest.mark.asyncio
async def test_scan_gives_up_as_a_real_failure_after_max_deadlock_retries(
    tmp_path: Path, db_session, monkeypatch
):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A")

    calls = {"count": 0}

    async def always_deadlocks(*args, **kwargs):
        calls["count"] += 1
        raise _FakeDeadlockError()

    monkeypatch.setattr(orchestrator_module, "_persist_module", always_deadlocks)

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")

    assert calls["count"] == 2  # _MAX_MODULE_PERSIST_ATTEMPTS, not retried forever
    assert done["result"].modules_created == 0
    assert len(done["result"].warnings) == 1
    assert "deadlock detected" in done["result"].warnings[0]


@pytest.mark.asyncio
async def test_scan_does_not_retry_a_non_deadlock_failure(tmp_path: Path, db_session, monkeypatch):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A")

    calls = {"count": 0}

    async def fails_with_something_else(*args, **kwargs):
        calls["count"] += 1
        raise RuntimeError("something unrelated broke")

    monkeypatch.setattr(orchestrator_module, "_persist_module", fails_with_something_else)

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")

    assert calls["count"] == 1  # no retry -- only deadlocks get one
    assert done["result"].modules_created == 0
    assert "something unrelated broke" in done["result"].warnings[0]
