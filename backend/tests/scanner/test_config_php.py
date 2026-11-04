from pathlib import Path

from app.scanner.config_php import parse_config_php


def test_parse_config_php(demo_store_path: Path):
    result = parse_config_php(demo_store_path / "app" / "etc" / "config.php")

    assert result == {"Magento_Sales": True, "Vendor_Module": True}


def test_parse_config_php_missing_file(tmp_path: Path):
    assert parse_config_php(tmp_path / "config.php") is None
