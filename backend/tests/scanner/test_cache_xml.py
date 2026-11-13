from pathlib import Path

from app.scanner.cache_xml import parse_cache_xml

_CACHE_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:App/Cache/etc/cache.xsd">
    <type name="vendor_module_sample" instance="Vendor\\Module\\Model\\Cache\\Type" translate="label,description">
        <label>Sample Cache</label>
        <description>A sample cache type.</description>
    </type>
</config>
"""


def test_parse_cache_xml(tmp_path: Path):
    path = tmp_path / "cache.xml"
    path.write_text(_CACHE_XML, encoding="utf-8")

    types = parse_cache_xml(path)

    assert len(types) == 1
    assert types[0].cache_type_id == "vendor_module_sample"
    assert types[0].instance == "Vendor\\Module\\Model\\Cache\\Type"


def test_parse_cache_xml_missing_file(tmp_path: Path):
    assert parse_cache_xml(tmp_path / "cache.xml") == []


def test_parse_cache_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "cache.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_cache_xml(path) == []


def test_parse_cache_xml_skips_type_without_name(tmp_path: Path):
    path = tmp_path / "cache.xml"
    path.write_text(
        '<?xml version="1.0"?><config><type instance="Vendor\\Module\\Model\\Cache\\Type"/></config>',
        encoding="utf-8",
    )
    assert parse_cache_xml(path) == []


def test_parse_cache_xml_allows_a_missing_instance(tmp_path: Path):
    path = tmp_path / "cache.xml"
    path.write_text('<?xml version="1.0"?><config><type name="label_only"/></config>', encoding="utf-8")
    types = parse_cache_xml(path)
    assert len(types) == 1
    assert types[0].cache_type_id == "label_only"
    assert types[0].instance is None
