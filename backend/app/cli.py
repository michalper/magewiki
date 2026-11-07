import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select, update

from app.db import async_session_factory
from app.models import FileHash, Module, ModuleDocument
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository
from app.tasks.queue import get_arq_pool


async def _run_scan(path: str) -> int:
    async with async_session_factory() as session:
        try:
            result = await scan_repository(path, session)
        except ScanAlreadyInProgressError as exc:
            print(f"error: {exc}")
            return 1

    print(f"Scanned {result.repo_root}")
    print(
        f"modules_found={result.modules_found} created={result.modules_created} "
        f"updated={result.modules_updated} classes={result.classes_total} "
        f"plugins={result.plugins_total} observers={result.observers_total} "
        f"tasks_enqueued={result.tasks_enqueued}"
    )
    for w in result.warnings:
        print(f"warning: {w}")
    for m in result.modules:
        print(
            f"  {m.status:8s} {m.name:40s} state={m.state:12s} classes={m.classes} "
            f"plugins={m.plugins} observers={m.observers} "
            f"files(+{m.files_added}/~{m.files_changed}/-{m.files_removed})"
        )
        for w in m.warnings:
            print(f"    warning: {w}")

    return 1 if any(m.status == "error" for m in result.modules) else 0


async def _resume_modules(modules: Sequence[Module], session) -> None:
    """Shared by resume-budget and resume-failed: re-enqueue each module from
    wherever it actually stopped — unanalyzed files first (ground truth via
    FileHash.analyzed, not the pending_file_count counter, which only reflects
    the most recent scan's diff and can be stale for a module resumed after a
    failure rather than a fresh scan), then synthesis if no ModuleDocument
    exists yet for the current hash, else embedding.
    """
    pool = await get_arq_pool()
    for module in modules:
        file_hashes = (
            await session.scalars(
                select(FileHash).where(FileHash.module_id == module.id, FileHash.analyzed.is_(False))
            )
        ).all()
        # pending_file_count must be reset to exactly what's being (re-)enqueued here,
        # not left at whatever stale value it already had: analyze_file's own
        # completion handler triggers synthesize_module only when its decrement lands
        # on EXACTLY 0 (Module.pending_file_count - 1) — resuming from a stale
        # nonzero/zero baseline makes that decrement skip past 0 forever, silently
        # stranding the module in "analyzing" with no job left to move it forward.
        # Confirmed in production: modules with 0 pending_file_count and 0 actually-
        # unanalyzed files were still stuck in "analyzing" with no module_docs row
        # and no job in the queue, after an earlier resume cycle.
        if file_hashes:
            for fh in file_hashes:
                job_id = f"analyze:{module.id}:{fh.relative_path}:{fh.content_hash}"
                await pool.enqueue_job(
                    "analyze_file",
                    module.id,
                    fh.relative_path,
                    fh.content_hash,
                    module.current_hash,
                    _job_id=job_id,
                )
            print(f"  resumed {module.name}: re-enqueued {len(file_hashes)} file(s)")
        else:
            doc_exists = await session.scalar(
                select(ModuleDocument.id).where(
                    ModuleDocument.module_id == module.id, ModuleDocument.content_hash == module.current_hash
                )
            )
            if doc_exists is not None:
                job_id = f"embed:{module.id}:{module.current_hash}"
                await pool.enqueue_job("embed_chunks", module.id, module.current_hash, _job_id=job_id)
                print(f"  resumed {module.name}: re-enqueued embedding")
            else:
                job_id = f"synthesize:{module.id}:{module.current_hash}"
                await pool.enqueue_job("synthesize_module", module.id, module.current_hash, _job_id=job_id)
                print(f"  resumed {module.name}: re-enqueued synthesis")

        await session.execute(
            update(Module)
            .where(Module.id == module.id, Module.current_hash == module.current_hash)
            .values(state="analyzing", pending_file_count=len(file_hashes))
        )
    await session.commit()


async def _run_resume_budget(repo_root: str | None) -> int:
    async with async_session_factory() as session:
        query = select(Module).where(Module.state == "paused_budget")
        if repo_root:
            query = query.where(Module.repo_root == str(Path(repo_root).resolve()))
        modules = (await session.scalars(query)).all()

        if not modules:
            print("No modules in paused_budget state.")
            return 0

        await _resume_modules(modules, session)

    return 0


async def _run_resume_failed(repo_root: str | None) -> int:
    async with async_session_factory() as session:
        query = select(Module).where(Module.state == "failed")
        if repo_root:
            query = query.where(Module.repo_root == str(Path(repo_root).resolve()))
        modules = (await session.scalars(query)).all()

        if not modules:
            print("No modules in failed state.")
            return 0

        await _resume_modules(modules, session)

    return 0


async def _run_resume_stuck(repo_root: str | None) -> int:
    """Modules sitting in 'analyzing'/'embedding' are mid-pipeline by design while
    their jobs are queued — but the pending_file_count-desync bug _resume_modules
    now guards against could already have stranded some with no job left in the
    queue at all before that fix existed. _resume_modules is idempotent either way
    (re-enqueuing a job ARQ already has queued is a harmless no-op via its job_id),
    so this is safe to run speculatively even on modules that are actually fine.
    """
    async with async_session_factory() as session:
        query = select(Module).where(Module.state.in_(("analyzing", "embedding")))
        if repo_root:
            query = query.where(Module.repo_root == str(Path(repo_root).resolve()))
        modules = (await session.scalars(query)).all()

        if not modules:
            print("No modules in analyzing/embedding state.")
            return 0

        await _resume_modules(modules, session)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a Magento repository or module")
    scan_parser.add_argument("path", help="Path to a Magento store root or a single module")

    resume_parser = subparsers.add_parser(
        "resume-budget", help="Re-enqueue analysis for modules paused by the monthly LLM budget"
    )
    resume_parser.add_argument("repo_root", nargs="?", help="Limit to modules under this repo root")

    resume_failed_parser = subparsers.add_parser(
        "resume-failed", help="Re-enqueue analysis for modules in the failed state, from wherever they stopped"
    )
    resume_failed_parser.add_argument("repo_root", nargs="?", help="Limit to modules under this repo root")

    resume_stuck_parser = subparsers.add_parser(
        "resume-stuck",
        help="Re-enqueue analysis for modules in analyzing/embedding with no job actually left in the queue "
        "(e.g. stranded by a since-fixed pending_file_count desync) — safe to run speculatively",
    )
    resume_stuck_parser.add_argument("repo_root", nargs="?", help="Limit to modules under this repo root")

    args = parser.parse_args(argv)

    if args.command == "scan":
        return asyncio.run(_run_scan(args.path))
    if args.command == "resume-budget":
        return asyncio.run(_run_resume_budget(args.repo_root))
    if args.command == "resume-failed":
        return asyncio.run(_run_resume_failed(args.repo_root))
    if args.command == "resume-stuck":
        return asyncio.run(_run_resume_stuck(args.repo_root))

    return 1


if __name__ == "__main__":
    sys.exit(main())
