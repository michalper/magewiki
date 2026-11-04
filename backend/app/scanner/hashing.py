import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from app.scanner.discovery import walk_module_php_files

_FIXED_FILES = ("etc/module.xml", "composer.json", "etc/di.xml", "etc/events.xml")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_module_file_hashes(module_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}

    for relative in _FIXED_FILES:
        path = module_root / relative
        if path.is_file():
            hashes[relative] = _sha256_file(path)

    for php_file in walk_module_php_files(module_root):
        relative_path = str(php_file.relative_to(module_root))
        hashes[relative_path] = _sha256_file(php_file)

    return hashes


def aggregate_hash(file_hashes: dict[str, str]) -> str:
    lines = "".join(f"{path}:{digest}\n" for path, digest in sorted(file_hashes.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


@dataclass
class FileDiff:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.removed)


def diff_file_hashes(old: dict[str, str], new: dict[str, str]) -> FileDiff:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    return FileDiff(added=added, changed=changed, removed=removed)
