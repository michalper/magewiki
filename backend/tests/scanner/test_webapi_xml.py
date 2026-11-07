from pathlib import Path

from app.scanner.webapi_xml import parse_webapi_xml

_WEBAPI_XML = """<?xml version="1.0"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:module:Magento_Webapi:etc/webapi.xsd">
    <route url="/V1/vendor-module/samples" method="GET">
        <service class="Vendor\\Module\\Api\\SampleRepositoryInterface" method="getList"/>
        <resources>
            <resource ref="Vendor_Module::samples"/>
        </resources>
    </route>
</routes>
"""


def test_parse_webapi_xml(tmp_path: Path):
    path = tmp_path / "webapi.xml"
    path.write_text(_WEBAPI_XML, encoding="utf-8")

    routes = parse_webapi_xml(path)

    assert len(routes) == 1
    route = routes[0]
    assert route.url == "/V1/vendor-module/samples"
    assert route.http_method == "GET"
    assert route.service_class == "Vendor\\Module\\Api\\SampleRepositoryInterface"
    assert route.service_method == "getList"
    assert route.acl_resource == "Vendor_Module::samples"


def test_parse_webapi_xml_missing_file(tmp_path: Path):
    assert parse_webapi_xml(tmp_path / "webapi.xml") == []


def test_parse_webapi_xml_route_without_resource(tmp_path: Path):
    path = tmp_path / "webapi.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<routes><route url="/V1/x" method="GET">'
        '<service class="Vendor\\Module\\Api\\X" method="getList"/>'
        "</route></routes>",
        encoding="utf-8",
    )

    routes = parse_webapi_xml(path)

    assert len(routes) == 1
    assert routes[0].acl_resource is None
