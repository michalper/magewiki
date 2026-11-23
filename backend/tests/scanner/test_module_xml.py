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


def test_parse_module_xml_invalid_bytes_in_the_declared_encoding(tmp_path: Path):
    """Same fuzzing-found regression as test_xml_parse_utils.py's equivalent
    test: lxml raises OSError, not XMLSyntaxError, for some byte sequences that
    don't decode under the file's own declared encoding."""
    bad_xml = tmp_path / "module.xml"
    bad_xml.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?><config>\xff\xfe</config>')

    with pytest.raises(InvalidModuleXmlError, match="malformed module.xml"):
        parse_module_xml(bad_xml)


def test_parse_module_xml_does_not_expand_an_xxe_entity(tmp_path: Path):
    """Same defense-in-depth regression as test_xml_parse_utils.py's
    equivalent test, for module_xml.py's own separate etree.parse() call."""
    secret = tmp_path.parent / "xxe_secret_module.txt"
    secret.write_text("super-secret-host-content")
    bad_xml = tmp_path / "module.xml"
    bad_xml.write_text(
        '<?xml version="1.0"?>'
        f'<!DOCTYPE module [ <!ENTITY xxe SYSTEM "file://{secret}"> ]>'
        '<config><module name="&xxe;"/></config>'
    )

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
