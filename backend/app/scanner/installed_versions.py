import json
from pathlib import Path


def parse_installed_versions(repo_root: Path) -> dict[str, str]:
    """Composer package name -> resolved installed version, from
    vendor/composer/installed.json — the authoritative record of what Composer
    actually installed, unlike a package's own composer.json (which often has no
    "version" key at all when installed from a VCS/dist reference) or Magento's
    setup_version (optional since Magento 2.3's declarative schema, and frequently
    absent entirely on modern modules — see CLAUDE.md's version-source note).
    Composer 2.x's installed.json is {"packages": [...], ...}; Composer 1.x's was a
    bare array — handle both.
    """
    path = repo_root / "vendor" / "composer" / "installed.json"
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}

    packages = raw.get("packages", []) if isinstance(raw, dict) else raw
    if not isinstance(packages, list):
        return {}

    versions: dict[str, str] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        name = pkg.get("name")
        version = pkg.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[name] = version
    return versions
