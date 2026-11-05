from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.analyzer.client import LlmCallResult
from app.analyzer.schemas import FileSummary
from app.models import AnalysisCache, FileAnalysis, FileHash, Module
from app.scanner.orchestrator import scan_repository
from app.tasks.jobs import analyze_file


async def _delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


def _fake_summarize_file(call_log: list[str]):
    async def _fake(relative_path: str, content: str):
        call_log.append(relative_path)
        summary = FileSummary(file_summary=f"Summary of {relative_path}", notable_behavior=None)
        result = LlmCallResult(
            response_json=summary.model_dump(), tokens_in=100, tokens_out=20, cost_usd=Decimal("0.001")
        )
        return summary, result

    return _fake


async def _scan_demo_store(demo_store_path: Path, session) -> Module:
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, session)
    return await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))


@pytest.mark.asyncio
async def test_analyze_file_calls_llm_once_then_uses_cache(demo_store_path: Path, db_session, monkeypatch):
    module = await _scan_demo_store(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash))
    await db_session.commit()

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.summarize_file", _fake_summarize_file(call_log))

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
    module = await _scan_demo_store(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "composer.json")
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == file_hash.content_hash))
    await db_session.commit()

    async def _always_exceeded(session):
        return True

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _always_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", _fake_summarize_file(call_log))

    await analyze_file(None, module.id, "composer.json", file_hash.content_hash, module.current_hash)

    assert call_log == []  # LLM never called once budget is exceeded
    await db_session.refresh(module)
    assert module.state == "paused_budget"
    await db_session.refresh(file_hash)
    assert file_hash.analyzed is False


@pytest.mark.asyncio
async def test_analyze_file_noop_on_stale_scan_generation(demo_store_path: Path, db_session):
    module = await _scan_demo_store(demo_store_path, db_session)

    # A job carrying a module_current_hash that no longer matches the module's
    # current_hash came from a scan generation that's since been superseded.
    await analyze_file(None, module.id, "etc/module.xml", "deadbeef", "stale-generation-hash")

    await db_session.refresh(module)
    assert module.pending_file_count == 7  # untouched
