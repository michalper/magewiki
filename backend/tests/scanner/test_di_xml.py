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


def test_parse_di_xml_missing_file(tmp_path: Path):
    result = parse_di_xml(tmp_path / "di.xml")

    assert result.preferences == []
    assert result.plugins == []
