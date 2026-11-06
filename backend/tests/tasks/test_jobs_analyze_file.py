from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

from app.models import AnalysisCache, FileAnalysis, FileHash, Module
from app.tasks.jobs import analyze_file
from tests.conftest import fake_summarize_file, scan_demo_store


@pytest.mark.asyncio
async def test_analyze_file_calls_llm_once_then_uses_cache(demo_store_path: Path, db_session, monkeypatch):
    module = await scan_demo_store(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash))
    await db_session.commit()

    async def _never_exceeded(session):
        return False

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _never_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", fake_summarize_file(call_log))

    await analyze_file(None, module.id, "etc/module.xml", file_hash.content_hash, module.current_hash)

    assert call_log == ["etc/module.xml"]

    cache_row = await db_session.scalar(
        select(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash)
    )
    assert cache_row is not None
    assert cache_row.cost_usd == Decimal("0.001000")

    fa = await db_session.scalar(
        select(FileAnalysis).where(FileAnalysis.module_id == module.id, FileAnalysis.relative_path == "etc/module.xml")
    )
    assert fa is not None
    assert fa.cache_id == cache_row.id

    await db_session.refresh(file_hash)
    assert file_hash.analyzed is True

    await db_session.refresh(module)
    assert module.pending_file_count == 6  # 7 total files - 1 just analyzed

    # A duplicate/retried job for the exact same (path, hash) must hit the cache,
    # not call the LLM again, and must not double-decrement pending_file_count.
    await analyze_file(None, module.id, "etc/module.xml", file_hash.content_hash, module.current_hash)
    assert call_log == ["etc/module.xml"]
    await db_session.refresh(module)
    assert module.pending_file_count == 6


@pytest.mark.asyncio
async def test_analyze_file_pauses_on_budget_exceeded(demo_store_path: Path, db_session, monkeypatch):
    module = await scan_demo_store(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "composer.json")
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash))
    await db_session.commit()

    async def _always_exceeded(session):
        return True

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _always_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", fake_summarize_file(call_log))

    await analyze_file(None, module.id, "composer.json", file_hash.content_hash, module.current_hash)

    assert call_log == []  # LLM never called once budget is exceeded
    await db_session.refresh(module)
    assert module.state == "paused_budget"
    await db_session.refresh(file_hash)
    assert file_hash.analyzed is False


@pytest.mark.asyncio
async def test_analyze_file_failure_does_not_clobber_a_newer_scan_generations_state(
    demo_store_path: Path, db_session, monkeypatch
):
    """Regression test: a job that fails AFTER a newer scan generation has already
    completed (module.current_hash changed and state moved on) must not overwrite
    that newer generation's state with 'failed' — the failure belongs to the old,
    now-irrelevant generation.
    """
    module = await scan_demo_store(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash))
    await db_session.commit()
    original_hash = module.current_hash

    async def _never_exceeded(session):
        return False

    async def _race_then_fail(relative_path: str, content: str, **kwargs):
        # Simulate a concurrent, newer scan completing while this (now-stale) job
        # was still in flight, calling the LLM.
        await db_session.execute(
            update(Module).where(Module.id == module.id).values(current_hash="newer-generation-hash", state="up_to_date")
        )
        await db_session.commit()
        raise RuntimeError("simulated LLM failure in the stale job")

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _never_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", _race_then_fail)

    with pytest.raises(RuntimeError):
        await analyze_file(None, module.id, "etc/module.xml", file_hash.content_hash, original_hash)

    await db_session.refresh(module)
    assert module.current_hash == "newer-generation-hash"
    assert module.state == "up_to_date"  # not clobbered back to "failed"


@pytest.mark.asyncio
async def test_analyze_file_noop_on_stale_scan_generation(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    # A job carrying a module_current_hash that no longer matches the module's
    # current_hash came from a scan generation that's since been superseded.
    await analyze_file(None, module.id, "etc/module.xml", "deadbeef", "stale-generation-hash")

    await db_session.refresh(module)
    assert module.pending_file_count == 7  # untouched
