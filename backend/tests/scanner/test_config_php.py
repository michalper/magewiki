from pathlib import Path

from app.scanner.config_php import _strip_quotes, parse_config_php


def test_parse_config_php(demo_store_path: Path):
    result = parse_config_php(demo_store_path / "app" / "etc" / "config.php")

    assert result == {"Magento_Sales": True, "Vendor_Module": True}


def test_parse_config_php_missing_file(tmp_path: Path):
    assert parse_config_php(tmp_path / "config.php") is None


def test_strip_quotes_returns_unquoted_text_unchanged():
    assert _strip_quotes("already_bare") == "already_bare"


def test_parse_config_php_returns_none_with_no_return_statement(tmp_path: Path):
    (tmp_path / "config.php").write_text("<?php\n$x = 1;\n", encoding="utf-8")
    assert parse_config_php(tmp_path / "config.php") is None


def test_parse_config_php_returns_none_when_the_return_value_is_not_an_array(tmp_path: Path):
    (tmp_path / "config.php").write_text("<?php\nreturn 'not an array';\n", encoding="utf-8")
    assert parse_config_php(tmp_path / "config.php") is None


def test_parse_config_php_returns_none_when_modules_is_not_an_array(tmp_path: Path):
    (tmp_path / "config.php").write_text(
        "<?php\nreturn [\n    'modules' => 'not an array',\n];\n", encoding="utf-8"
    )
    assert parse_config_php(tmp_path / "config.php") is None


def test_parse_config_php_returns_none_with_no_modules_key(tmp_path: Path):
    (tmp_path / "config.php").write_text(
        "<?php\nreturn [\n    'scopes' => [],\n];\n", encoding="utf-8"
    )
    assert parse_config_php(tmp_path / "config.php") is None


def test_parse_config_php_skips_a_non_binary_module_value_and_a_non_modules_sibling_key(tmp_path: Path):
    (tmp_path / "config.php").write_text(
        "<?php\nreturn [\n"
        "    'scopes' => [],\n"
        "    'modules' => [\n"
        "        'Vendor_Weird' => SOME_CONSTANT,\n"
        "        'Vendor_Real' => 1,\n"
        "    ],\n"
        "];\n",
        encoding="utf-8",
    )
    result = parse_config_php(tmp_path / "config.php")
    assert result == {"Vendor_Real": True}
