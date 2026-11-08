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
    config = raw.get("config") if isinstance(raw.get("config"), dict) else {}

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
        scripts=_script_names(raw.get("scripts")),
        autoload_psr4=_autoload_psr4(autoload.get("psr-4")),
        allow_plugins=_allow_plugins(config.get("allow-plugins")),
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


def _script_names(raw_scripts: object) -> list[str]:
    if not isinstance(raw_scripts, dict):
        return []
    return sorted(name for name in raw_scripts if isinstance(name, str))


def _autoload_psr4(raw_psr4: object) -> dict[str, str]:
    """composer.json's autoload.psr-4 maps a namespace to either a single path
    string or an array of paths — normalized to one string per namespace so
    the API/frontend don't need to handle both shapes. Keys are always
    strings here (json.loads never produces non-string object keys), so no
    separate key-type guard is needed, unlike the value, which genuinely
    varies in shape.
    """
    if not isinstance(raw_psr4, dict):
        return {}
    result: dict[str, str] = {}
    for namespace, target in raw_psr4.items():
        if isinstance(target, str):
            result[namespace] = target
        elif isinstance(target, list):
            result[namespace] = ", ".join(str(p) for p in target)
    return result


def _allow_plugins(raw_allow_plugins: object) -> dict[str, bool]:
    if not isinstance(raw_allow_plugins, dict):
        return {}
    return {name: value for name, value in raw_allow_plugins.items() if isinstance(value, bool)}


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
