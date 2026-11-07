from pathlib import Path

from app.scanner.system_xml import parse_system_xml

_SYSTEM_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:module:Magento_Config:etc/system_file.xsd">
    <system>
        <section id="vendor_module" translate="label" type="text" sortOrder="10">
            <label>Vendor Module</label>
            <group id="general" translate="label" type="text" sortOrder="10">
                <label>General</label>
                <field id="enabled" translate="label" type="select" sortOrder="10">
                    <label>Enabled</label>
                </field>
            </group>
        </section>
    </system>
</config>
"""


def test_parse_system_xml(tmp_path: Path):
    path = tmp_path / "system.xml"
    path.write_text(_SYSTEM_XML, encoding="utf-8")

    fields = parse_system_xml(path)

    assert len(fields) == 1
    field = fields[0]
    assert field.section_id == "vendor_module"
    assert field.group_id == "general"
    assert field.field_id == "enabled"
    assert field.label == "Enabled"
    assert field.field_type == "select"


def test_parse_system_xml_missing_file(tmp_path: Path):
    assert parse_system_xml(tmp_path / "system.xml") == []


def test_parse_system_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "system.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_system_xml(path) == []


def test_parse_system_xml_skips_sections_groups_and_fields_without_an_id(tmp_path: Path):
    path = tmp_path / "system.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        "<config><system>"
        '<section><group id="g"><field id="f"/></group></section>'
        '<section id="s"><group><field id="f"/></group></section>'
        '<section id="s"><group id="g"><field/></group></section>'
        "</system></config>",
        encoding="utf-8",
    )
    assert parse_system_xml(path) == []
