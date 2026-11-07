import json
from pathlib import Path

from app.scanner.dto import ComposerResult, QualityFinding


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

    require = raw.get("require") if isinstance(raw.get("require"), dict) else {}
    require_dev = raw.get("require-dev") if isinstance(raw.get("require-dev"), dict) else {}
    autoload = raw.get("autoload") if isinstance(raw.get("autoload"), dict) else {}

    return ComposerResult(
        name=raw.get("name"),
        type=raw.get("type"),
        license=license_list,
        description=raw.get("description"),
        version=raw.get("version") if isinstance(raw.get("version"), str) else None,
        has_php_requirement=bool(require.get("php")),
        php_constraint=str(require["php"]) if require.get("php") else None,
        has_magento_dependency=any(k.startswith("magento/") for k in require),
        has_autoload_psr4=bool(autoload.get("psr-4")),
        has_autoload_files=bool(autoload.get("files")),
        has_phpunit_dev_dependency="phpunit/phpunit" in require_dev,
        requirements=_third_party_packages(require),
        dev_requirements=_third_party_packages(require_dev),
        homepage=raw.get("homepage") if isinstance(raw.get("homepage"), str) else None,
        authors=_authors(raw.get("authors")),
        php_extensions=sorted(name for name in require if name.startswith("ext-")),
    )


def _authors(raw_authors: object) -> list[str]:
    if not isinstance(raw_authors, list):
        return []
    formatted = []
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if not isinstance(name, str) or not name:
            continue
        email = author.get("email")
        formatted.append(f"{name} <{email}>" if isinstance(email, str) and email else name)
    return formatted


def _third_party_packages(require: dict) -> dict[str, str]:
    """Real installable packages only — excludes the "php" platform entry and
    "ext-*"/"lib-*" platform-capability pseudo-packages, which have no
    Packagist page and no version constraint worth checking for advisories.
    """
    return {
        name: str(constraint)
        for name, constraint in require.items()
        if "/" in name and not name.startswith(("ext-", "lib-"))
    }


def composer_completeness_findings(result: ComposerResult | None) -> list[QualityFinding]:
    """Missing-field heuristic over an already-parsed composer.json. A module
    with no composer.json at all produces no findings here — that's a
    different, more fundamental problem than an incomplete one.
    """
    if result is None:
        return []

    findings: list[QualityFinding] = []

    def _check(present: bool, field: str) -> None:
        if not present:
            findings.append(
                QualityFinding(
                    check_type="composer_completeness",
                    severity="warning",
                    file_path="composer.json",
                    line=None,
                    message=f"composer.json is missing {field}",
                )
            )

    _check(bool(result.name), "name")
    _check(bool(result.description), "description")
    _check(bool(result.type), "type")
    _check(bool(result.license), "license")
    _check(result.has_php_requirement, "require.php")
    _check(result.has_magento_dependency, "a magento/* dependency in require")
    _check(result.has_autoload_psr4, "autoload.psr-4")
    _check(result.has_autoload_files, "autoload.files")
    _check(result.has_phpunit_dev_dependency, "require-dev phpunit/phpunit")

    return findings
