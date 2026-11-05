import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select, update

from app.db import async_session_factory
from app.models import FileHash, Module
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


async def _run_resume_budget(repo_root: str | None) -> int:
    async with async_session_factory() as session:
        query = select(Module).where(Module.state == "paused_budget")
        if repo_root:
            query = query.where(Module.repo_root == str(Path(repo_root).resolve()))
        modules = (await session.scalars(query)).all()

        if not modules:
            print("No modules in paused_budget state.")
            return 0

        pool = await get_arq_pool()
        for module in modules:
            if module.pending_file_count > 0:
                file_hashes = (
                    await session.scalars(
                        select(FileHash).where(FileHash.module_id == module.id, FileHash.analyzed.is_(False))
                    )
                ).all()
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
                job_id = f"synthesize:{module.id}:{module.current_hash}"
                await pool.enqueue_job("synthesize_module", module.id, module.current_hash, _job_id=job_id)
                print(f"  resumed {module.name}: re-enqueued synthesis")

            await session.execute(
                update(Module)
                .where(Module.id == module.id, Module.current_hash == module.current_hash)
                .values(state="analyzing")
            )
        await session.commit()

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

    args = parser.parse_args(argv)

    if args.command == "scan":
        return asyncio.run(_run_scan(args.path))
    if args.command == "resume-budget":
        return asyncio.run(_run_resume_budget(args.repo_root))

    return 1


if __name__ == "__main__":
    sys.exit(main())
