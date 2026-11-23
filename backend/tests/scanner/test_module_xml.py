from pathlib import Path

import pytest

from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml


def test_parse_module_xml(demo_module_path: Path):
    result = parse_module_xml(demo_module_path / "etc" / "module.xml")

    assert result.name == "Vendor_Module"
    assert result.setup_version == "1.0.0"
    assert result.sequence == ["Magento_Sales"]


def test_parse_module_xml_missing_module_element(tmp_path: Path):
    bad_xml = tmp_path / "module.xml"
    bad_xml.write_text('<?xml version="1.0"?><config></config>')

    with pytest.raises(InvalidModuleXmlError):
        parse_module_xml(bad_xml)


def test_parse_module_xml_malformed_xml(tmp_path: Path):
    bad_xml = tmp_path / "module.xml"
    bad_xml.write_text("<config><unclosed>")

    with pytest.raises(InvalidModuleXmlError, match="malformed module.xml"):
        parse_module_xml(bad_xml)


def test_parse_module_xml_refuses_a_symlink(tmp_path: Path):
    """Security regression: must never follow a symlinked module.xml to
    read an arbitrary host path (a real symlink, not a mock)."""
    outside = tmp_path.parent / "outside_module.xml"
    outside.write_text('<?xml version="1.0"?><config><module name="Evil"/></config>')
    link = tmp_path / "module.xml"
    link.symlink_to(outside)

    with pytest.raises(InvalidModuleXmlError, match="symlink"):
        parse_module_xml(link)
