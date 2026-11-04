import os
from pathlib import Path

from app.scanner.dto import DiscoveredModule

_PRUNE_ALWAYS = {".git", "node_modules"}
_STORE_SOURCE_DIRS = (("app/code", "app_code"), ("vendor", "vendor"))


def find_modules(repo_root: Path) -> list[DiscoveredModule]:
    """Find Magento module roots under `repo_root`.

    Two cases:
    - `repo_root` is itself a single module (its own etc/module.xml sits at the
      root) — scanning a standalone module checkout.
    - `repo_root` is a store root — walk app/code and vendor for etc/module.xml.

    Once a module root is found, walking stops there: this both prevents
    descending into that module's own nested vendor/ directory and prevents
    treating anything inside it as a separate module.
    """
    if (repo_root / "etc" / "module.xml").is_file():
        return [DiscoveredModule(root=repo_root, relative_path=Path("."), source_type="standalone")]

    discovered: list[DiscoveredModule] = []
    for source_dir, source_type in _STORE_SOURCE_DIRS:
        scan_root = repo_root / source_dir
        if not scan_root.is_dir():
            continue
        for dirpath, dirnames, _filenames in os.walk(scan_root, topdown=True):
            current = Path(dirpath)
            if (current / "etc" / "module.xml").is_file():
                discovered.append(
                    DiscoveredModule(
                        root=current,
                        relative_path=current.relative_to(repo_root),
                        source_type=source_type,
                    )
                )
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in _PRUNE_ALWAYS]

    return discovered


def walk_module_php_files(module_root: Path) -> list[Path]:
    """List all .php files under a module root, excluding nested vendor/ and .git."""
    php_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(module_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in (_PRUNE_ALWAYS | {"vendor"})]
        for filename in filenames:
            if filename.endswith(".php"):
                php_files.append(Path(dirpath) / filename)
    return php_files
