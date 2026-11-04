import json
from pathlib import Path

from app.scanner.dto import ComposerResult


def parse_composer_json(path: Path) -> ComposerResult | None:
    if not path.is_file():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    license_raw = raw.get("license")
    if isinstance(license_raw, str):
        license_list = [license_raw]
    elif isinstance(license_raw, list):
        license_list = [str(item) for item in license_raw]
    else:
        license_list = None

    return ComposerResult(
        name=raw.get("name"),
        type=raw.get("type"),
        license=license_list,
    )
