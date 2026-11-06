from pathlib import Path


def _looks_like_a_store_or_module_root(path: Path) -> bool:
    """Same signals find_modules() itself relies on to recognize a scannable
    unit — a standalone module (etc/module.xml at the root) or a store root
    (app/code and/or vendor present).
    """
    return (
        (path / "etc" / "module.xml").is_file()
        or (path / "app" / "code").is_dir()
        or (path / "vendor").is_dir()
    )


def find_store_roots(path: Path) -> list[Path]:
    """Expand `path` into one or more scannable store/module roots.

    On a real server, many stores commonly live side by side under one
    parent directory (e.g. `/sites/store-a`, `/sites/store-b`, ...) — scanning
    all of them today means one manual `POST /scan` per store. If `path`
    itself already looks like a store or module root, it's returned as-is
    (today's single-store case, unchanged). Otherwise its immediate
    subdirectories that look like a store/module root are returned, sorted
    for deterministic ordering; subdirectories that don't qualify (logs,
    backups, unrelated folders) are silently skipped rather than treated as
    an error, matching find_modules()'s own fail-quiet style. Returns `[]`
    if nothing at or under `path` qualifies.
    """
    if _looks_like_a_store_or_module_root(path):
        return [path]

    if not path.is_dir():
        return []

    return sorted(
        (child for child in path.iterdir() if child.is_dir() and _looks_like_a_store_or_module_root(child)),
        key=lambda p: p.name,
    )
