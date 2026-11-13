from pathlib import Path

from app.scanner.routes_xml import parse_routes_xml

_ROUTES_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:App/etc/routes.xsd">
    <router id="standard">
        <route id="vendor_module" frontName="vendormodule">
            <module name="Vendor_Module" />
        </route>
    </router>
</config>
"""


def test_parse_routes_xml(tmp_path: Path):
    path = tmp_path / "routes.xml"
    path.write_text(_ROUTES_XML, encoding="utf-8")

    routes = parse_routes_xml(path, "frontend")

    assert len(routes) == 1
    assert routes[0].area == "frontend"
    assert routes[0].route_id == "vendor_module"
    assert routes[0].front_name == "vendormodule"


def test_parse_routes_xml_tags_the_area_passed_in(tmp_path: Path):
    path = tmp_path / "routes.xml"
    path.write_text(_ROUTES_XML, encoding="utf-8")

    routes = parse_routes_xml(path, "adminhtml")

    assert routes[0].area == "adminhtml"


def test_parse_routes_xml_missing_file(tmp_path: Path):
    assert parse_routes_xml(tmp_path / "routes.xml", "frontend") == []


def test_parse_routes_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "routes.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_routes_xml(path, "frontend") == []


def test_parse_routes_xml_skips_a_route_missing_id_or_frontname(tmp_path: Path):
    path = tmp_path / "routes.xml"
    path.write_text(
        '<?xml version="1.0"?><config><router id="standard">'
        '<route frontName="noid"><module name="Vendor_Module" /></route>'
        '<route id="nofrontname"><module name="Vendor_Module" /></route>'
        "</router></config>",
        encoding="utf-8",
    )
    assert parse_routes_xml(path, "frontend") == []
