import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from app.scanner.discovery import is_safe_to_read, walk_module_source_files

# Every relative path orchestrator.py's Phase A parses into a structural fact
# (ConfigField, CronJob, WebapiRoute, DbTable, AclResource, Indexer, Mview,
# RouteConfig, Widget, MenuItem, CacheType, QueueBinding, ...) must be hashed
# here too -- otherwise an XML-only change to one of them leaves the module's
# aggregate_hash unchanged, so the module never goes back to "pending" and its
# AI-written README/ModuleDoc (config_options, features, etc. -- see
# build_module_synthesis_prompt) never gets regenerated to reflect a fact that
# *did* get persisted. A new fact source added in a later phase belongs in
# both places, and in orchestrator.py's Phase A in the same change.
_FIXED_FILES = (
    "etc/module.xml",
    "composer.json",
    "etc/di.xml",
    "etc/events.xml",
    "etc/schema.graphqls",
    "etc/crontab.xml",
    "etc/webapi.xml",
    "etc/adminhtml/system.xml",
    "etc/db_schema.xml",
    "etc/communication.xml",
    "etc/queue_topology.xml",
    "etc/queue_consumer.xml",
    "etc/acl.xml",
    "etc/indexer.xml",
    "etc/mview.xml",
    "etc/frontend/routes.xml",
    "etc/adminhtml/routes.xml",
    "view/base/widget.xml",
    "view/frontend/widget.xml",
    "view/adminhtml/widget.xml",
    "etc/adminhtml/menu.xml",
    "etc/cache.xml",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_module_file_hashes(module_root: Path, php_sources: dict[str, bytes] | None = None) -> dict[str, str]:
    """Hashes every fixed structural-fact file plus every .php/.phtml source file.

    `php_sources` lets a caller that already read every source file's bytes once
    (orchestrator.py's read_module_source_files(), shared with catalog_module_
    classes' tree-sitter parse) hash from that same in-memory content instead of
    reading each file from disk again here — otherwise every PHP/phtml file in a
    module got read from disk twice per scan. Omitting it (every existing direct
    caller/test) falls back to reading the files here, unchanged.
    """
    hashes: dict[str, str] = {}

    for relative in _FIXED_FILES:
        path = module_root / relative
        if path.is_file() and is_safe_to_read(path):
            hashes[relative] = _sha256_file(path)

    if php_sources is not None:
        for relative_path, content in php_sources.items():
            hashes[relative_path] = hashlib.sha256(content).hexdigest()
    else:
        for php_file in walk_module_source_files(module_root):
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
