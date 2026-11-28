from pathlib import Path

from app.scanner.email_templates_xml import parse_email_templates_xml

_EMAIL_TEMPLATES_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:module:Magento_Email:etc/email_templates.xsd">
    <template id="vendor_module_welcome" label="Welcome Email" file="welcome.html" type="html" module="Vendor_Module" area="frontend"/>
</config>
"""


def test_parse_email_templates_xml(tmp_path: Path):
    path = tmp_path / "email_templates.xml"
    path.write_text(_EMAIL_TEMPLATES_XML, encoding="utf-8")

    templates = parse_email_templates_xml(path)

    assert len(templates) == 1
    assert templates[0].template_id == "vendor_module_welcome"
    assert templates[0].label == "Welcome Email"
    assert templates[0].file == "welcome.html"
    assert templates[0].type == "html"
    assert templates[0].area == "frontend"


def test_parse_email_templates_xml_missing_file(tmp_path: Path):
    assert parse_email_templates_xml(tmp_path / "email_templates.xml") == []


def test_parse_email_templates_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "email_templates.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_email_templates_xml(path) == []


def test_parse_email_templates_xml_skips_template_without_id(tmp_path: Path):
    path = tmp_path / "email_templates.xml"
    path.write_text('<?xml version="1.0"?><config><template label="No id"/></config>', encoding="utf-8")
    assert parse_email_templates_xml(path) == []


def test_parse_email_templates_xml_allows_missing_optional_attributes(tmp_path: Path):
    path = tmp_path / "email_templates.xml"
    path.write_text('<?xml version="1.0"?><config><template id="bare_template"/></config>', encoding="utf-8")
    templates = parse_email_templates_xml(path)
    assert len(templates) == 1
    assert templates[0].template_id == "bare_template"
    assert templates[0].label is None
    assert templates[0].file is None
    assert templates[0].type is None
    assert templates[0].area is None
