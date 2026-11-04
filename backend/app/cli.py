import argparse
import asyncio
import sys

from app.db import async_session_factory
from app.scanner.orchestrator import scan_repository


async def _run_scan(path: str) -> int:
    async with async_session_factory() as session:
        result = await scan_repository(path, session)

    print(f"Scanned {result.repo_root}")
    print(
        f"modules_found={result.modules_found} created={result.modules_created} "
        f"updated={result.modules_updated} classes={result.classes_total} "
        f"plugins={result.plugins_total} observers={result.observers_total}"
    )
    for w in result.warnings:
        print(f"warning: {w}")
    for m in result.modules:
        print(f"  {m.status:8s} {m.name:40s} classes={m.classes} plugins={m.plugins} observers={m.observers}")
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
