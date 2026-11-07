from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.cli import _run_resume_failed
from app.models import AnalysisCache, FileHash, Module, ModuleDocument
from app.scanner.orchestrator import scan_repository
from app.tasks.queue import get_arq_pool
from tests.conftest import delete_module_if_present


async def _scan_and_fail(demo_store_path: Path, db_session) -> Module:
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)
    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))
    await db_session.execute(update(Module).where(Module.id == module.id).values(state="failed"))
    await db_session.commit()
    await db_session.refresh(module)
    return module


@pytest.mark.asyncio
async def test_resume_failed_requeues_unanalyzed_files(demo_store_path: Path, db_session):
    module = await _scan_and_fail(demo_store_path, db_session)
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    expected_job_id = f"analyze:{module.id}:etc/module.xml:{file_hash.content_hash}"

    assert await _run_resume_failed(None) == 0

    pool = await get_arq_pool()
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert expected_job_id in queued_ids


@pytest.mark.asyncio
async def test_resume_failed_requeues_synthesis_once_files_are_analyzed(demo_store_path: Path, db_session):
    module = await _scan_and_fail(demo_store_path, db_session)
    await db_session.execute(update(FileHash).where(FileHash.module_id == module.id).values(analyzed=True))
    await db_session.commit()

    assert await _run_resume_failed(None) == 0

    pool = await get_arq_pool()
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert f"synthesize:{module.id}:{module.current_hash}" in queued_ids


@pytest.mark.asyncio
async def test_resume_failed_requeues_embedding_once_a_module_doc_exists(demo_store_path: Path, db_session):
    module = await _scan_and_fail(demo_store_path, db_session)
    await db_session.execute(update(FileHash).where(FileHash.module_id == module.id).values(analyzed=True))
    cache = AnalysisCache(
        content_hash=module.current_hash,
        model="anthropic/claude-sonnet-5-5",
        prompt_version="v1",
        kind="module_synthesis",
        response={},
        tokens_in=1,
        tokens_out=1,
        cost_usd=Decimal(0),
    )
    db_session.add(cache)
    await db_session.flush()
    db_session.add(
        ModuleDocument(
            module_id=module.id,
            content_hash=module.current_hash,
            model="anthropic/claude-sonnet-5-5",
            prompt_version="v1",
            cache_id=cache.id,
            doc={},
        )
    )
    await db_session.commit()

    assert await _run_resume_failed(None) == 0

    pool = await get_arq_pool()
    queued_ids = {job.job_id for job in await pool.queued_jobs()}
    assert f"embed:{module.id}:{module.current_hash}" in queued_ids


@pytest.mark.asyncio
async def test_resume_failed_reports_when_nothing_is_failed(db_session):
    await db_session.execute(update(Module).where(Module.state == "failed").values(state="up_to_date"))
    await db_session.commit()
    assert await _run_resume_failed(None) == 0
