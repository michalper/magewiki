from pathlib import Path

from app.scanner.acl_xml import parse_acl_xml

_ACL_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:Acl/etc/acl.xsd">
    <acl>
        <resources>
            <resource id="Vendor_Module::top" title="Top">
                <resource id="Vendor_Module::child" title="Child"/>
            </resource>
        </resources>
    </acl>
</config>
"""


def test_parse_acl_xml(tmp_path: Path):
    path = tmp_path / "acl.xml"
    path.write_text(_ACL_XML, encoding="utf-8")

    resources = parse_acl_xml(path)

    by_id = {r.resource_id: r for r in resources}
    assert set(by_id) == {"Vendor_Module::top", "Vendor_Module::child"}
    assert by_id["Vendor_Module::top"].title == "Top"
    assert by_id["Vendor_Module::top"].parent_id is None
    assert by_id["Vendor_Module::child"].parent_id == "Vendor_Module::top"


def test_parse_acl_xml_missing_file(tmp_path: Path):
    assert parse_acl_xml(tmp_path / "acl.xml") == []


def test_parse_acl_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "acl.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_acl_xml(path) == []


def test_parse_acl_xml_no_resources(tmp_path: Path):
    path = tmp_path / "acl.xml"
    path.write_text('<?xml version="1.0"?><config><acl/></config>', encoding="utf-8")
    assert parse_acl_xml(path) == []


def test_parse_acl_xml_resource_without_id_is_skipped(tmp_path: Path):
    path = tmp_path / "acl.xml"
    path.write_text(
        '<?xml version="1.0"?><config><acl><resources><resource title="No id"/></resources></acl></config>',
        encoding="utf-8",
    )
    assert parse_acl_xml(path) == []
