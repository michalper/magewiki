import os
from pathlib import Path

_PRUNE = {".git", "node_modules", "vendor"}
_TEST_DIR_NAMES = {"Test", "Tests"}


def has_tests(module_root: Path) -> bool:
    """Directory/filename heuristic only — detects whether a test suite
    exists, never executes it."""
    for dirpath, dirnames, filenames in os.walk(module_root, topdown=True):
        if Path(dirpath).name in _TEST_DIR_NAMES:
            return True
        dirnames[:] = [d for d in dirnames if d not in _PRUNE]
        for filename in filenames:
            if filename.endswith("Test.php") or filename in ("phpunit.xml", "phpunit.xml.dist"):
                return True
    return False
