import os
from pathlib import Path

from app.scanner.composer_repositories import find_path_repository_globs
from app.scanner.dto import DiscoveredModule

_PRUNE_ALWAYS = {".git", "node_modules"}
_STORE_SOURCE_DIRS = (("app/code", "app_code"), ("vendor", "vendor"))


def _find_module_roots(scan_root: Path, repo_root: Path, source_type: str) -> list[DiscoveredModule]:
    """Walk `scan_root` for etc/module.xml, stopping descent at each match —
    this both prevents descending into that module's own nested vendor/
    directory and prevents treating anything inside it as a separate module.
    """
    if (scan_root / "etc" / "module.xml").is_file():
        return [
            DiscoveredModule(root=scan_root, relative_path=scan_root.relative_to(repo_root), source_type=source_type)
        ]

    found: list[DiscoveredModule] = []
    for dirpath, dirnames, _filenames in os.walk(scan_root, topdown=True):
        current = Path(dirpath)
        if (current / "etc" / "module.xml").is_file():
            found.append(
                DiscoveredModule(
                    root=current, relative_path=current.relative_to(repo_root), source_type=source_type
                )
            )
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_ALWAYS]

    return found


def find_modules(repo_root: Path) -> list[DiscoveredModule]:
    """Find Magento module roots under `repo_root`.

    Two cases:
    - `repo_root` is itself a single module (its own etc/module.xml sits at the
      root) — scanning a standalone module checkout.
    - `repo_root` is a store root — walk app/code and vendor for etc/module.xml,
      plus whatever the root composer.json's own Composer "path" repositories
      declare (e.g. `"repositories": {"local": {"type": "path", "url":
      "src/*/*"}}`) — a common way to install in-house/monorepo-style modules
      that live entirely outside app/code and vendor.
    """
    if (repo_root / "etc" / "module.xml").is_file():
        return [DiscoveredModule(root=repo_root, relative_path=Path("."), source_type="standalone")]

    discovered: list[DiscoveredModule] = []
    for source_dir, source_type in _STORE_SOURCE_DIRS:
        scan_root = repo_root / source_dir
        if scan_root.is_dir():
            discovered.extend(_find_module_roots(scan_root, repo_root, source_type))

    for glob_pattern in find_path_repository_globs(repo_root / "composer.json"):
        for match in repo_root.glob(glob_pattern):
            if match.is_dir():
                discovered.extend(_find_module_roots(match, repo_root, "composer_path"))

    # Dedupe by resolved real path — belt-and-suspenders against the same
    # module being reached twice (e.g. overlapping path-repository glob
    # patterns). Doesn't currently need to cover "also symlinked into
    # vendor/": os.walk()'s default followlinks=False means it never visits
    # a symlinked directory as a dirpath in the first place (verified
    # directly), so the vendor/ walk can't double-discover it that way.
    seen_roots: set[Path] = set()
    deduped: list[DiscoveredModule] = []
    for module in discovered:
        resolved = module.root.resolve()
        if resolved not in seen_roots:
            seen_roots.add(resolved)
            deduped.append(module)
    return deduped


_SOURCE_FILE_SUFFIXES = (".php", ".phtml")


def walk_module_source_files(module_root: Path) -> list[Path]:
    """List all .php/.phtml files under a module root, excluding nested vendor/ and
    .git. Used for both per-file hashing/LLM analysis (hashing.py) and PHP class
    cataloging (php_classes.py) — .phtml templates have no top-level class to
    extract, so tree-sitter just finds zero classes for them there, harmlessly.
    """
    source_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(module_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in (_PRUNE_ALWAYS | {"vendor"})]
        for filename in filenames:
            if filename.endswith(_SOURCE_FILE_SUFFIXES):
                source_files.append(Path(dirpath) / filename)
    return source_files
