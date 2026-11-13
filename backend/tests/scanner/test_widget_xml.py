from pathlib import Path

from app.scanner.widget_xml import parse_widget_xml

_WIDGET_XML = """<?xml version="1.0"?>
<widgets xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:Data/etc/widget.xsd">
    <widget id="vendor_module_sample" class="Vendor\\Module\\Block\\Widget\\Sample">
        <label translate="true">Sample Widget</label>
    </widget>
</widgets>
"""


def test_parse_widget_xml(tmp_path: Path):
    path = tmp_path / "widget.xml"
    path.write_text(_WIDGET_XML, encoding="utf-8")

    widgets = parse_widget_xml(path)

    assert len(widgets) == 1
    assert widgets[0].widget_id == "vendor_module_sample"
    assert widgets[0].class_name == "Vendor\\Module\\Block\\Widget\\Sample"


def test_parse_widget_xml_missing_file(tmp_path: Path):
    assert parse_widget_xml(tmp_path / "widget.xml") == []


def test_parse_widget_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "widget.xml"
    path.write_text("<widgets><unclosed>", encoding="utf-8")
    assert parse_widget_xml(path) == []


def test_parse_widget_xml_skips_widget_without_id_or_class(tmp_path: Path):
    path = tmp_path / "widget.xml"
    path.write_text(
        '<?xml version="1.0"?><widgets><widget class="Vendor\\Module\\Block\\Widget\\Sample"/>'
        '<widget id="no_class"/></widgets>',
        encoding="utf-8",
    )
    assert parse_widget_xml(path) == []
