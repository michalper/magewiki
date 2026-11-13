from pathlib import Path

from app.scanner.indexer_xml import parse_indexer_xml

_INDEXER_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:Indexer/etc/indexer.xsd">
    <indexer id="vendor_module_sample" view_id="vendor_module_sample" class="Vendor\\Module\\Indexer\\Sample">
        <title translate="true">Sample Indexer</title>
    </indexer>
</config>
"""


def test_parse_indexer_xml(tmp_path: Path):
    path = tmp_path / "indexer.xml"
    path.write_text(_INDEXER_XML, encoding="utf-8")

    indexers = parse_indexer_xml(path)

    assert len(indexers) == 1
    assert indexers[0].indexer_id == "vendor_module_sample"
    assert indexers[0].view_id == "vendor_module_sample"
    assert indexers[0].class_name == "Vendor\\Module\\Indexer\\Sample"


def test_parse_indexer_xml_missing_file(tmp_path: Path):
    assert parse_indexer_xml(tmp_path / "indexer.xml") == []


def test_parse_indexer_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "indexer.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_indexer_xml(path) == []


def test_parse_indexer_xml_skips_indexer_without_id(tmp_path: Path):
    path = tmp_path / "indexer.xml"
    path.write_text(
        '<?xml version="1.0"?><config><indexer class="Vendor\\Module\\Indexer\\Sample"/></config>',
        encoding="utf-8",
    )
    assert parse_indexer_xml(path) == []
