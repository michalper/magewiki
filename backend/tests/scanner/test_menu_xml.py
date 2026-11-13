from pathlib import Path

from app.scanner.menu_xml import parse_menu_xml

_MENU_XML = """<?xml version="1.0"?>
<menu xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:module:Magento_Backend:etc/menu.xsd">
    <add id="vendor_module_sample" title="Sample" module="Vendor_Module" sortOrder="10" resource="Vendor_Module::sample"/>
</menu>
"""


def test_parse_menu_xml(tmp_path: Path):
    path = tmp_path / "menu.xml"
    path.write_text(_MENU_XML, encoding="utf-8")

    items = parse_menu_xml(path)

    assert len(items) == 1
    assert items[0].menu_item_id == "vendor_module_sample"
    assert items[0].title == "Sample"


def test_parse_menu_xml_missing_file(tmp_path: Path):
    assert parse_menu_xml(tmp_path / "menu.xml") == []


def test_parse_menu_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "menu.xml"
    path.write_text("<menu><unclosed>", encoding="utf-8")
    assert parse_menu_xml(path) == []


def test_parse_menu_xml_skips_add_without_id(tmp_path: Path):
    path = tmp_path / "menu.xml"
    path.write_text('<?xml version="1.0"?><menu><add title="No id"/></menu>', encoding="utf-8")
    assert parse_menu_xml(path) == []


def test_parse_menu_xml_allows_a_missing_title(tmp_path: Path):
    path = tmp_path / "menu.xml"
    path.write_text('<?xml version="1.0"?><menu><add id="no_title"/></menu>', encoding="utf-8")
    items = parse_menu_xml(path)
    assert len(items) == 1
    assert items[0].menu_item_id == "no_title"
    assert items[0].title is None
