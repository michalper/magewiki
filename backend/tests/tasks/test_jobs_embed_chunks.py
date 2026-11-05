from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.analyzer.client import LlmCallResult
from app.analyzer.schemas import FileSummary, ModuleDoc
from app.models import AnalysisCache, Chunk, FileHash, Module, ModuleDocument
from app.scanner.orchestrator import scan_repository
from app.tasks.jobs import analyze_file, embed_chunks, synthesize_module


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


def _fake_summarize_file():
    async def _fake(relative_path: str, content: str, **kwargs):
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


def _fake_embed_text(call_log: list[str]):
    async def _fake(text: str, **kwargs):
        call_log.append(text)
        vector = [0.0] * 1536
        vector[len(text) % 1536] = 1.0
        result = LlmCallResult(
            response_json={"embedding": vector}, tokens_in=10, tokens_out=0, cost_usd=Decimal("0.0001")
        )
        return vector, result

    return _fake


async def _reach_embedding_state(demo_store_path: Path, session, monkeypatch) -> Module:
    module = await _scan_demo_store(demo_store_path, session)

    # These tests fake out the LLM entirely and must not depend on the real,
    # cumulative monthly spend tracked in analysis_cache — only the dedicated
    # budget test re-patches this to True for its own embed_chunks call.
    async def _never_exceeded(session):
        return False

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _never_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", _fake_summarize_file())
    file_hashes = (await session.scalars(select(FileHash).where(FileHash.module_id == module.id))).all()
    for fh in file_hashes:
        await session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == fh.content_hash))
    await session.commit()
    for fh in file_hashes:
        await analyze_file(None, module.id, fh.relative_path, fh.content_hash, module.current_hash)

    await session.refresh(module)
    await session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == module.current_hash))
    await session.commit()

    fake_doc = _fake_doc()

    async def _fake_synthesize(facts, known_sources, **kwargs):
        result = LlmCallResult(
            response_json=fake_doc.model_dump(mode="json"), tokens_in=500, tokens_out=100, cost_usd=Decimal("0.01")
        )
        return fake_doc, result

    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)
    await synthesize_module(None, module.id, module.current_hash)

    await session.refresh(module)
    assert module.state == "embedding"

    # Chunk content (module/file/method text) is identical across test runs against
    # this fixture, so a leftover embedding-cache row from a previous test would
    # silently turn this run's misses into hits. Isolate each test from that.
    await session.execute(delete(AnalysisCache).where(AnalysisCache.kind == "embedding"))
    await session.execute(delete(Chunk).where(Chunk.module_id == module.id))
    await session.commit()

    return module


@pytest.mark.asyncio
async def test_embed_chunks_builds_module_file_and_method_chunks(demo_store_path: Path, db_session, monkeypatch):
    module = await _reach_embedding_state(demo_store_path, db_session, monkeypatch)

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.embed_text", _fake_embed_text(call_log))

    await embed_chunks(None, module.id, module.current_hash)

    assert len(call_log) == 10  # 1 module + 7 file + 2 method (plugin + observer), all cache misses

    chunks = (await db_session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
    assert len(chunks) == 10
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1
    assert by_type == {"module": 1, "file": 7, "method": 2}

    method_chunk = next(
        c for c in chunks if c.chunk_type == "method" and c.relative_path == "Plugin/SampleCheckoutPlugin.php"
    )
    assert "beforeSubmitAll" in method_chunk.text
    assert "return [$items];" in method_chunk.text

    await db_session.refresh(module)
    assert module.state == "up_to_date"
    assert module.analyzed_hash == module.current_hash
    assert module.last_error is None

    # A re-run (duplicate job, or resume-budget) must hit the cache for every chunk.
    call_log.clear()
    await embed_chunks(None, module.id, module.current_hash)
    assert call_log == []
    chunks_after = (await db_session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
    assert len(chunks_after) == 10


@pytest.mark.asyncio
async def test_embed_chunks_pauses_on_budget_exceeded(demo_store_path: Path, db_session, monkeypatch):
    module = await _reach_embedding_state(demo_store_path, db_session, monkeypatch)

    async def _always_exceeded(session):
        return True

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _always_exceeded)
    monkeypatch.setattr("app.tasks.jobs.embed_text", _fake_embed_text(call_log))

    await embed_chunks(None, module.id, module.current_hash)

    assert call_log == []
    await db_session.refresh(module)
    assert module.state == "paused_budget"

    chunks = (await db_session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
    assert chunks == []


@pytest.mark.asyncio
async def test_embed_chunks_noop_on_stale_scan_generation(demo_store_path: Path, db_session, monkeypatch):
    module = await _reach_embedding_state(demo_store_path, db_session, monkeypatch)

    await embed_chunks(None, module.id, "stale-generation-hash")

    await db_session.refresh(module)
    assert module.state == "embedding"  # untouched
    chunks = (await db_session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
    assert chunks == []


@pytest.mark.asyncio
async def test_embed_chunks_noop_when_module_doc_missing(demo_store_path: Path, db_session, monkeypatch):
    module = await _scan_demo_store(demo_store_path, db_session)

    doc_row = await db_session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module.id))
    assert doc_row is None

    await embed_chunks(None, module.id, module.current_hash)

    chunks = (await db_session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
    assert chunks == []
