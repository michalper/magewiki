from pathlib import Path

from app.scanner.composer_json import parse_composer_json


def test_parse_composer_json_with_array_license(demo_module_path: Path):
    result = parse_composer_json(demo_module_path / "composer.json")

    assert result.name == "vendor/module-sample"
    assert result.type == "magento2-module"
    assert result.license == ["MIT", "OSL-3.0"]


def test_parse_composer_json_missing_file(tmp_path: Path):
    assert parse_composer_json(tmp_path / "composer.json") is None
