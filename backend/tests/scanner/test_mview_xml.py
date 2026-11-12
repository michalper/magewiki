from pathlib import Path

from app.scanner.mview_xml import parse_mview_xml

_MVIEW_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:Mview/etc/mview.xsd">
    <view id="vendor_module_sample" class="Vendor\\Module\\Mview\\Sample" group="indexer">
        <subscriptions>
            <table name="vendor_module_sample_table" entity_column="entity_id"/>
        </subscriptions>
    </view>
</config>
"""


def test_parse_mview_xml(tmp_path: Path):
    path = tmp_path / "mview.xml"
    path.write_text(_MVIEW_XML, encoding="utf-8")

    mviews = parse_mview_xml(path)

    assert len(mviews) == 1
    assert mviews[0].view_id == "vendor_module_sample"
    assert mviews[0].class_name == "Vendor\\Module\\Mview\\Sample"
    assert mviews[0].group_name == "indexer"


def test_parse_mview_xml_missing_file(tmp_path: Path):
    assert parse_mview_xml(tmp_path / "mview.xml") == []


def test_parse_mview_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "mview.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_mview_xml(path) == []


def test_parse_mview_xml_skips_view_without_id(tmp_path: Path):
    path = tmp_path / "mview.xml"
    path.write_text(
        '<?xml version="1.0"?><config><view class="Vendor\\Module\\Mview\\Sample"/></config>',
        encoding="utf-8",
    )
    assert parse_mview_xml(path) == []
