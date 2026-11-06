import json
from pathlib import Path

from app.scanner.composer_repositories import find_path_repository_globs


def test_finds_path_type_in_object_keyed_repositories(tmp_path: Path):
    composer_json = tmp_path / "composer.json"
    composer_json.write_text(
        json.dumps(
            {
                "repositories": {
                    "local": {"type": "path", "url": "src/*/*"},
                    "magento": {"type": "composer", "url": "https://repo.magento.com/"},
                }
            }
        )
    )

    assert find_path_repository_globs(composer_json) == ["src/*/*"]


def test_finds_path_type_in_legacy_array_repositories(tmp_path: Path):
    composer_json = tmp_path / "composer.json"
    composer_json.write_text(
        json.dumps({"repositories": [{"type": "path", "url": "custom/*"}, {"type": "vcs", "url": "git@x"}]})
    )

    assert find_path_repository_globs(composer_json) == ["custom/*"]


def test_returns_empty_list_when_no_repositories_key(tmp_path: Path):
    composer_json = tmp_path / "composer.json"
    composer_json.write_text(json.dumps({"name": "vendor/module"}))

    assert find_path_repository_globs(composer_json) == []


def test_returns_empty_list_when_file_missing(tmp_path: Path):
    assert find_path_repository_globs(tmp_path / "composer.json") == []


def test_returns_empty_list_on_malformed_json(tmp_path: Path):
    composer_json = tmp_path / "composer.json"
    composer_json.write_text("{not valid json")

    assert find_path_repository_globs(composer_json) == []
