import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.analyzer.client import LlmCallResult
from app.models import AnalysisCache, Chunk, PhpClass
from app.scanner.orchestrator import ScanAlreadyInProgressError
from app.tasks import jobs as jobs_module
from app.tasks.jobs import (
    _get_or_create_cache_entry,
    embed_chunks,
    refresh_magento_release_cache,
    scan_repository_job,
)
from tests.tasks.test_jobs_embed_chunks import _fake_embed_text, _reach_embedding_state


@pytest.mark.asyncio
async def test_get_or_create_cache_entry_inserts_a_new_row(db_session):
    content_hash = f"jobs-misc-{uuid.uuid4().hex[:8]}"
    result = LlmCallResult(response_json={"x": 1}, tokens_in=10, tokens_out=5, cost_usd=Decimal("0.001"))

    cache_id = await _get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", result)
    await db_session.commit()

    row = await db_session.get(AnalysisCache, cache_id)
    assert row is not None
    assert row.content_hash == content_hash


@pytest.mark.asyncio
async def test_get_or_create_cache_entry_returns_the_existing_id_on_conflict(db_session):
    """Regression/race-condition path: on_conflict_do_nothing() means a concurrent
    job that already inserted the identical (content_hash, model, prompt_version,
    kind) row wins -- this call must find and return THAT row's id, not silently
    produce no id or a duplicate.
    """
    content_hash = f"jobs-misc-race-{uuid.uuid4().hex[:8]}"
    first_result = LlmCallResult(response_json={"x": 1}, tokens_in=10, tokens_out=5, cost_usd=Decimal("0.001"))
    existing_id = await _get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", first_result)
    await db_session.commit()

    second_result = LlmCallResult(response_json={"x": 2}, tokens_in=99, tokens_out=99, cost_usd=Decimal(9))
    returned_id = await _get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", second_result)

    assert returned_id == existing_id

    rows = (
        await db_session.scalars(
            select(AnalysisCache).where(
                AnalysisCache.content_hash == content_hash, AnalysisCache.model == "m",
                AnalysisCache.prompt_version == "v1", AnalysisCache.kind == "file_summary",
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].tokens_in == 10  # the first (winning) insert's data, not the second's


@pytest.mark.asyncio
async def test_embed_chunks_falls_back_to_empty_source_when_a_method_file_is_unreadable(
    demo_store_path: Path, db_session, monkeypatch
):
    module = await _reach_embedding_state(demo_store_path, db_session, monkeypatch)

    plugin_class = await db_session.scalar(
        select(PhpClass).where(PhpClass.module_id == module.id, PhpClass.is_plugin.is_(True))
    )
    await db_session.execute(
        update(PhpClass).where(PhpClass.id == plugin_class.id).values(file_path="NoSuchFile/DoesNotExist.php")
    )
    await db_session.commit()

    call_log: list[str] = []
    monkeypatch.setattr("app.tasks.jobs.embed_text", _fake_embed_text(call_log))

    await embed_chunks(None, module.id, module.current_hash)

    method_chunk = await db_session.scalar(
        select(Chunk).where(Chunk.module_id == module.id, Chunk.chunk_type == "method", Chunk.method_id.isnot(None))
    )
    assert method_chunk is not None
    # build_method_chunk_text(fqcn, method_name, "") -- empty source, not a crash.
    assert method_chunk.text.endswith("\n\n")


@pytest.mark.asyncio
async def test_scan_repository_job_calls_the_real_scan(demo_store_path: Path, db_session, monkeypatch):
    called = {}

    async def _fake_scan(repo_root, session):
        called["repo_root"] = repo_root

    monkeypatch.setattr(jobs_module, "scan_repository", _fake_scan)

    await scan_repository_job(None, str(demo_store_path))

    assert called["repo_root"] == str(demo_store_path)


@pytest.mark.asyncio
async def test_scan_repository_job_swallows_scan_already_in_progress(monkeypatch):
    async def _raise(repo_root, session):
        raise ScanAlreadyInProgressError(f"a scan of {repo_root} is already in progress")

    monkeypatch.setattr(jobs_module, "scan_repository", _raise)

    await scan_repository_job(None, "/some/path")  # must not raise


@pytest.mark.asyncio
async def test_refresh_magento_release_cache_warns_when_no_release_resolves(monkeypatch, caplog):
    async def _fake_resolve(session):
        return None

    monkeypatch.setattr(jobs_module, "resolve_latest_release", _fake_resolve)

    async def _unexpected_call(*args, **kwargs):
        raise AssertionError("must not be called when no release resolves")

    monkeypatch.setattr(jobs_module, "fetch_release_php_constraint", _unexpected_call)
    monkeypatch.setattr(jobs_module, "fetch_release_component_versions", _unexpected_call)

    with caplog.at_level("WARNING"):
        await refresh_magento_release_cache(None)

    assert "could not resolve the latest Magento release" in caplog.text


@pytest.mark.asyncio
async def test_refresh_magento_release_cache_fetches_and_commits_when_a_release_resolves(monkeypatch):
    calls = []

    async def _fake_resolve(session):
        return "2.4.8"

    async def _fake_php_constraint(session, tag):
        calls.append(("php", tag))
        return ">=8.1"

    async def _fake_component_versions(session, tag):
        calls.append(("components", tag))
        return {"magento/framework": "103.0.0"}

    monkeypatch.setattr(jobs_module, "resolve_latest_release", _fake_resolve)
    monkeypatch.setattr(jobs_module, "fetch_release_php_constraint", _fake_php_constraint)
    monkeypatch.setattr(jobs_module, "fetch_release_component_versions", _fake_component_versions)

    await refresh_magento_release_cache(None)

    assert ("php", "2.4.8") in calls
    assert ("components", "2.4.8") in calls
