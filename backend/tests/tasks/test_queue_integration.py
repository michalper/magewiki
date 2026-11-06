import shutil
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.models import FileHash, Module
from app.scanner.orchestrator import scan_repository
from app.tasks.queue import get_arq_pool


async def _delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


@pytest.mark.asyncio
async def test_scan_enqueues_a_real_job_on_the_arq_queue(demo_store_path: Path, db_session):
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    result = await scan_repository(repo_root, db_session)
    assert result.tasks_enqueued == 7

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    file_hash = await db_session.scalar(
        select(FileHash).where(FileHash.module_id == module.id, FileHash.relative_path == "etc/module.xml")
    )
    expected_job_id = f"analyze:{module.id}:etc/module.xml:{file_hash.content_hash}"

    pool = await get_arq_pool()
    queued = await pool.queued_jobs()
    queued_ids = {job.job_id for job in queued}

    assert expected_job_id in queued_ids


@pytest.mark.asyncio
async def test_scan_enqueues_synthesize_directly_for_a_removal_only_diff(
    demo_store_path: Path, db_session, tmp_path: Path
):
    """A diff with only removed files leaves pending_file_count at 0 — no
    analyze_file job exists to ever decrement it to 0 and trigger
    synthesize_module, so the scan must enqueue synthesize_module itself or
    the module (and its now-stale chunks for the deleted file) stays stuck in
    'pending' forever.
    """
    repo_copy = tmp_path / "demo-store"
    shutil.copytree(demo_store_path, repo_copy)
    repo_root = str(repo_copy.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")

    first = await scan_repository(repo_root, db_session)
    assert first.tasks_enqueued == 7

    observer_file = repo_copy / "app/code/Vendor/Module/Observer/SampleOrderObserver.php"
    observer_file.unlink()

    second = await scan_repository(repo_root, db_session)
    assert second.modules[0].files_removed == 1
    assert second.modules[0].files_added == 0
    assert second.modules[0].files_changed == 0
    assert second.tasks_enqueued == 0  # no analyze_file jobs — nothing added/changed

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module")
    )
    assert module.state == "pending"
    assert module.pending_file_count == 0

    pool = await get_arq_pool()
    queued = await pool.queued_jobs()
    queued_ids = {job.job_id for job in queued}
    expected_synthesize_job_id = f"synthesize:{module.id}:{module.current_hash}"

    assert expected_synthesize_job_id in queued_ids
