from pathlib import Path

from app.scanner.composer_json import composer_completeness_findings, parse_composer_json


def test_parse_composer_json_with_array_license(demo_module_path: Path):
    result = parse_composer_json(demo_module_path / "composer.json")

    assert result.name == "vendor/module-sample"
    assert result.type == "magento2-module"
    assert result.license == ["MIT", "OSL-3.0"]
    assert result.description == "Sample fixture module for scanner tests"
    assert result.has_php_requirement is True
    assert result.has_magento_dependency is True
    assert result.has_autoload_psr4 is True
    assert result.has_autoload_files is True
    assert result.has_phpunit_dev_dependency is False


def test_parse_composer_json_missing_file(tmp_path: Path):
    assert parse_composer_json(tmp_path / "composer.json") is None


def test_composer_completeness_findings_flags_only_whats_actually_missing(demo_module_path: Path):
    result = parse_composer_json(demo_module_path / "composer.json")
    findings = composer_completeness_findings(result)

    assert len(findings) == 1
    assert findings[0].check_type == "composer_completeness"
    assert findings[0].severity == "warning"
    assert "require-dev phpunit/phpunit" in findings[0].message


def test_composer_completeness_findings_flags_every_missing_field(tmp_path: Path):
    composer_json = tmp_path / "composer.json"
    composer_json.write_text("{}")
    result = parse_composer_json(composer_json)

    findings = composer_completeness_findings(result)

    assert {f.message for f in findings} == {
        "composer.json is missing name",
        "composer.json is missing description",
        "composer.json is missing type",
        "composer.json is missing license",
        "composer.json is missing require.php",
        "composer.json is missing a magento/* dependency in require",
        "composer.json is missing autoload.psr-4",
        "composer.json is missing autoload.files",
        "composer.json is missing require-dev phpunit/phpunit",
    }


def test_composer_completeness_findings_with_no_composer_json():
    assert composer_completeness_findings(None) == []
