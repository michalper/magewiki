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
