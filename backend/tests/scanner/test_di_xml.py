from pathlib import Path

from app.scanner.di_xml import parse_di_xml


def test_parse_di_xml(demo_module_path: Path):
    result = parse_di_xml(demo_module_path / "etc" / "di.xml")

    assert len(result.preferences) == 1
    pref = result.preferences[0]
    assert pref.for_type == "Vendor\\Module\\Api\\SampleInterface"
    assert pref.preference_type == "Vendor\\Module\\Model\\Sample"

    assert len(result.plugins) == 1
    plugin = result.plugins[0]
    assert plugin.intercepted_type == "Magento\\Quote\\Model\\Quote\\Address\\Total\\Collector"
    assert plugin.plugin_class == "Vendor\\Module\\Plugin\\SampleCheckoutPlugin"
    assert plugin.sort_order == 10
    assert plugin.disabled is False

    assert len(result.virtual_types) == 1
    virtual_type = result.virtual_types[0]
    assert virtual_type.name == "Vendor\\Module\\SampleCollectionFactory"
    assert virtual_type.virtual_type == "Vendor\\Module\\Model\\ResourceModel\\Sample\\CollectionFactory"


def test_parse_di_xml_missing_file(tmp_path: Path):
    result = parse_di_xml(tmp_path / "di.xml")

    assert result.preferences == []
    assert result.plugins == []
    assert result.virtual_types == []


def test_parse_di_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "di.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    result = parse_di_xml(path)
    assert result.preferences == []
    assert result.plugins == []
    assert result.virtual_types == []


def test_parse_di_xml_skips_a_type_without_a_name_and_a_plugin_missing_attributes(tmp_path: Path):
    path = tmp_path / "di.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        "<config>"
        '<type><plugin name="x" type="Vendor\\Module\\Plugin\\X"/></type>'
        '<type name="Vendor\\Module\\Model\\Real"><plugin type="NoNameAttr"/></type>'
        "</config>",
        encoding="utf-8",
    )
    result = parse_di_xml(path)
    assert result.plugins == []
