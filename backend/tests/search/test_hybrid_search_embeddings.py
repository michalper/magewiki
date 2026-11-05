from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.analyzer.client import LlmCallResult
from app.analyzer.schemas import ModuleDoc
from app.models import AnalysisCache, FileAnalysis, Module
from app.scanner.orchestrator import scan_repository
from app.search.hybrid import hybrid_search
from app.tasks.jobs import embed_chunks, synthesize_module
from tests.conftest import requires_openai_key


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


async def _seed_file_summary(session, module: Module, relative_path: str, content_hash: str, summary: str) -> None:
    fa = await session.scalar(
        select(FileAnalysis).where(FileAnalysis.module_id == module.id, FileAnalysis.relative_path == relative_path)
    )
    cache = AnalysisCache(
        content_hash=content_hash,
        model="seeded",
        prompt_version="seeded",
        kind="file_summary",
        response={"file_summary": summary, "notable_behavior": None},
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
    )
    session.add(cache)
    await session.flush()
    fa.cache_id = cache.id


@requires_openai_key
@pytest.mark.embeddings
@pytest.mark.asyncio
async def test_hybrid_search_ranks_real_embeddings_by_meaning(demo_store_path: Path, db_session, monkeypatch):
    """Real OpenAI embeddings (no mocking of embed_text/embed_query_text) must rank a
    chunk that's actually about the query's meaning above one that isn't — the
    honest end-to-end check of Phase 4's "a query returns the right files"
    criterion, independent of live-Anthropic phrasing variance.
    """
    module = await _scan_demo_store(demo_store_path, db_session)

    await _seed_file_summary(
        db_session,
        module,
        "Plugin/SampleCheckoutPlugin.php",
        "seeded-checkout-summary",
        "Blocks checkout submission when the customer's credit limit has been exceeded.",
    )
    await _seed_file_summary(
        db_session,
        module,
        "Observer/SampleOrderObserver.php",
        "seeded-other-summary",
        "Logs a timestamp whenever a new customer account is registered.",
    )
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == module.current_hash))
    await db_session.commit()

    fake_doc = _fake_doc()

    async def _fake_synthesize(facts, known_sources):
        result = LlmCallResult(
            response_json=fake_doc.model_dump(mode="json"), tokens_in=0, tokens_out=0, cost_usd=Decimal("0")
        )
        return fake_doc, result

    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)
    await synthesize_module(None, module.id, module.current_hash)

    await db_session.refresh(module)
    assert module.state == "embedding"

    await embed_chunks(None, module.id, module.current_hash)
    await db_session.refresh(module)
    assert module.state == "up_to_date"

    results = await hybrid_search(db_session, "credit limit checkout", limit=5)
    assert results, "expected at least one search result"
    assert results[0].relative_path == "Plugin/SampleCheckoutPlugin.php"
