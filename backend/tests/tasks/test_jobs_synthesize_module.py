from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.analyzer.client import LlmCallResult
from app.analyzer.schemas import FileSummary, ModuleDoc
from app.models import AnalysisCache, FileHash, Module, ModuleDocument
from app.scanner.orchestrator import scan_repository
from app.tasks.jobs import analyze_file, synthesize_module


async def _delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


async def _scan_demo_store(demo_store_path: Path, session) -> Module:
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, session)
    return await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))


def _fake_summarize_file(call_log: list[str]):
    async def _fake(relative_path: str, content: str, **kwargs):
        call_log.append(relative_path)
        summary = FileSummary(file_summary=f"Summary of {relative_path}", notable_behavior=None)
        result = LlmCallResult(
            response_json=summary.model_dump(), tokens_in=100, tokens_out=20, cost_usd=Decimal("0.001")
        )
        return summary, result

    return _fake


def _fake_doc() -> ModuleDoc:
    return ModuleDoc(
        summary="A module that does things.",
        description="Longer description of what it does.",
        features=[],
        integrations=[],
        tags=[],
        config_options=[],
        risks=[],
        confidence=0.9,
        pm_text="Business-level description.",
        dev_text="Developer-level description.",
    )


async def _analyze_all_files(module: Module, session, monkeypatch) -> None:
    monkeypatch.setattr("app.tasks.jobs.summarize_file", _fake_summarize_file([]))

    file_hashes = (await session.scalars(select(FileHash).where(FileHash.module_id == module.id))).all()
    for fh in file_hashes:
        await session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == fh.content_hash))
    await session.commit()

    for fh in file_hashes:
        await analyze_file(None, module.id, fh.relative_path, fh.content_hash, module.current_hash)


@pytest.mark.asyncio
async def test_synthesize_module_writes_doc_and_marks_up_to_date(demo_store_path: Path, db_session, monkeypatch):
    module = await _scan_demo_store(demo_store_path, db_session)
    await _analyze_all_files(module, db_session, monkeypatch)

    await db_session.refresh(module)
    assert module.pending_file_count == 0

    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == module.current_hash))
    await db_session.commit()

    call_log: list[str] = []
    fake_doc = _fake_doc()

    async def _fake_synthesize(facts, known_sources, **kwargs):
        call_log.append("called")
        result = LlmCallResult(
            response_json=fake_doc.model_dump(mode="json"), tokens_in=500, tokens_out=100, cost_usd=Decimal("0.01")
        )
        return fake_doc, result

    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)

    await synthesize_module(None, module.id, module.current_hash)

    assert call_log == ["called"]

    doc_row = await db_session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module.id))
    assert doc_row is not None
    assert doc_row.doc["summary"] == fake_doc.summary
    assert doc_row.content_hash == module.current_hash

    await db_session.refresh(module)
    assert module.state == "embedding"
    assert module.analyzed_hash is None  # not set until embed_chunks finishes the pipeline
    assert module.last_error is None

    # A re-run (e.g. a duplicate job) must hit the cache, not call the LLM again.
    await synthesize_module(None, module.id, module.current_hash)
    assert call_log == ["called"]


@pytest.mark.asyncio
async def test_synthesize_module_pauses_on_budget_exceeded(demo_store_path: Path, db_session, monkeypatch):
    module = await _scan_demo_store(demo_store_path, db_session)
    await _analyze_all_files(module, db_session, monkeypatch)
    await db_session.refresh(module)
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == module.current_hash))
    await db_session.commit()

    async def _always_exceeded(session):
        return True

    call_log: list[str] = []

    async def _fake_synthesize(facts, known_sources, **kwargs):
        call_log.append("called")
        raise AssertionError("should not be called when budget is exceeded")

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _always_exceeded)
    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)

    await synthesize_module(None, module.id, module.current_hash)

    assert call_log == []
    await db_session.refresh(module)
    assert module.state == "paused_budget"

    doc_row = await db_session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module.id))
    assert doc_row is None


@pytest.mark.asyncio
async def test_synthesize_module_noop_on_stale_scan_generation(demo_store_path: Path, db_session, monkeypatch):
    module = await _scan_demo_store(demo_store_path, db_session)

    await synthesize_module(None, module.id, "stale-generation-hash")

    await db_session.refresh(module)
    assert module.state == "pending"  # untouched, still whatever the scan set it to
    doc_row = await db_session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module.id))
    assert doc_row is None
