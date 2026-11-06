from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AnalysisCache, FileAnalysis, FileHash, Module, ModuleDocument
from app.scanner.orchestrator import scan_repository
from app.tasks.jobs import analyze_file, synthesize_module
from tests.conftest import delete_module_if_present, requires_anthropic_key


@requires_anthropic_key
@pytest.mark.llm
@pytest.mark.asyncio
async def test_real_llm_analyzes_demo_store_and_renders_readme(demo_store_path: Path, db_session):
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")

    result = await scan_repository(repo_root, db_session)
    assert result.tasks_enqueued == 7

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )

    file_hashes = (await db_session.scalars(select(FileHash).where(FileHash.module_id == module.id))).all()
    assert len(file_hashes) == 7

    for fh in file_hashes:
        await analyze_file(None, module.id, fh.relative_path, fh.content_hash, module.current_hash)

    file_analyses = (
        await db_session.scalars(select(FileAnalysis).where(FileAnalysis.module_id == module.id))
    ).all()
    assert len(file_analyses) == 7
    for fa in file_analyses:
        cache = await db_session.get(AnalysisCache, fa.cache_id)
        assert cache.cost_usd > 0
        assert cache.response.get("file_summary")

    await db_session.refresh(module)
    assert module.pending_file_count == 0

    await synthesize_module(None, module.id, module.current_hash)

    await db_session.refresh(module)
    assert module.state == "embedding"  # pipeline hands off to embed_chunks (Phase 4) before up_to_date
    assert module.analyzed_hash is None

    doc_row = await db_session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module.id))
    assert doc_row is not None
    assert doc_row.doc["summary"]
    assert doc_row.doc["features"]
    for feature in doc_row.doc["features"]:
        assert feature["source"]

    cache_row = await db_session.get(AnalysisCache, doc_row.cache_id)
    assert cache_row.cost_usd > 0

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/readme")

    assert response.status_code == 200
    assert "Vendor_Module" in response.text
    assert "source:" in response.text.lower()
