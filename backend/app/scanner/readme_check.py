from pathlib import Path

_README_NAMES = ("README.md", "Readme.md", "README.txt")


def has_readme(module_root: Path) -> bool:
    for name in _README_NAMES:
        candidate = module_root / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return True
    return False
