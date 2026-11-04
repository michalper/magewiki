import argparse
import asyncio
import sys

from app.db import async_session_factory
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a Magento repository or module")
    scan_parser.add_argument("path", help="Path to a Magento store root or a single module")

    args = parser.parse_args(argv)

    if args.command == "scan":
        return asyncio.run(_run_scan(args.path))

    return 1


if __name__ == "__main__":
    sys.exit(main())
