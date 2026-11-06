import json
from pathlib import Path


def find_path_repository_globs(composer_json_path: Path) -> list[str]:
    """Composer "path" repositories (`"repositories": {"local": {"type": "path",
    "url": "src/*/*"}}`) are a common way to install in-house/monorepo-style
    modules that live entirely outside app/code and vendor — invisible to
    find_modules() otherwise. Returns the raw glob strings from every
    `"type": "path"` entry's `"url"`; Composer supports both the legacy
    array-of-objects `repositories` form and the newer object-keyed-by-name
    form, so both are handled. Fails quiet (empty list) on any missing
    file/key/malformed JSON, same convention as parse_composer_json — this
    is a nice-to-have discovery aid, not something that should ever break a
    scan.
    """
    if not composer_json_path.is_file():
        return []

    try:
        raw = json.loads(composer_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []

    repositories = raw.get("repositories")
    entries: list = []
    if isinstance(repositories, dict):
        entries = list(repositories.values())
    elif isinstance(repositories, list):
        entries = repositories
    else:
        return []

    globs: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("type") == "path" and isinstance(entry.get("url"), str):
            globs.append(entry["url"])
    return globs
