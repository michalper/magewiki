import json
from pathlib import Path

from app.scanner.installed_versions import parse_installed_versions


def test_parse_installed_versions_missing_file(tmp_path: Path):
    assert parse_installed_versions(tmp_path) == {}


def test_parse_installed_versions_composer2_shape(tmp_path: Path):
    composer_dir = tmp_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text(
        json.dumps({"packages": [{"name": "amasty/base", "version": "1.21.0"}]}), encoding="utf-8"
    )

    assert parse_installed_versions(tmp_path) == {"amasty/base": "1.21.0"}


def test_parse_installed_versions_composer1_bare_array_shape(tmp_path: Path):
    composer_dir = tmp_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text(
        json.dumps([{"name": "amasty/base", "version": "1.21.0"}]), encoding="utf-8"
    )

    assert parse_installed_versions(tmp_path) == {"amasty/base": "1.21.0"}


def test_parse_installed_versions_malformed_json_returns_empty(tmp_path: Path):
    composer_dir = tmp_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text("not valid json", encoding="utf-8")

    assert parse_installed_versions(tmp_path) == {}


def test_parse_installed_versions_returns_empty_when_packages_is_not_a_list(tmp_path: Path):
    composer_dir = tmp_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text(json.dumps({"packages": "not a list"}), encoding="utf-8")

    assert parse_installed_versions(tmp_path) == {}


def test_parse_installed_versions_skips_a_non_dict_package_entry(tmp_path: Path):
    composer_dir = tmp_path / "vendor" / "composer"
    composer_dir.mkdir(parents=True)
    (composer_dir / "installed.json").write_text(
        json.dumps({"packages": ["not a dict", {"name": "amasty/base", "version": "1.21.0"}]}), encoding="utf-8"
    )

    assert parse_installed_versions(tmp_path) == {"amasty/base": "1.21.0"}
